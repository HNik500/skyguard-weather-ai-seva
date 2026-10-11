"""
Automated test suite verifying the end-to-end synchronization between
Test Lab (Live Fault Injection), Live Map marker state, prompt targeted
evaluation, and Incident Reports provenance in SkyGuard AI.
"""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.anomaly.detector import AnomalyDetector
from app.incidents import db as incident_db
from app.incidents import service as incident_service
from app.pipeline import events as ev
from app.pipeline.models import ObservationIn
from app.pipeline.runtime import PipelineRuntime, get_runtime, set_runtime
from app.pipeline.store import TimeSeriesStore
from app.sources.simulation import FaultBook, SimStation
from app.stations.service import station_service

UTC = timezone.utc


class TestLiveFaultInjectionSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_env = {k: os.environ.get(k) for k in ("ATHER_INCIDENTS_DB_PATH", "ATHER_TIMESERIES_DB_PATH")}
        os.environ["ATHER_INCIDENTS_DB_PATH"] = os.path.join(self.tmp, "incidents.db")
        os.environ["ATHER_TIMESERIES_DB_PATH"] = os.path.join(self.tmp, "ts.db")
        incident_db.reset_for_tests()

        detector = AnomalyDetector()
        store = TimeSeriesStore(path=os.path.join(self.tmp, "ts.db"))
        self.rt = PipelineRuntime(
            detector=detector,
            station_service=station_service,
            incident_service=incident_service,
            store=store,
            sim_enabled=True,
            reference_enabled=False,
            sim_interval_s=600,
        )
        set_runtime(self.rt)

        self.sid = "TEST-SYNC-01"
        self.all_sids = [f"TEST-SYNC-0{i+1}" for i in range(3)]
        self.stn_dict = {
            "id": self.sid,
            "localityId": "LOC-TEST",
            "name": "Sync Test AWS",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "elevation": 5.0,
            "country": "India",
            "region": "Karnataka",
            "town": "Bengaluru",
            "status": "NORMAL",
        }
        for i, sid in enumerate(self.all_sids):
            station_service._stations[sid] = {
                "id": sid,
                "localityId": "LOC-TEST",
                "name": f"Sync Test AWS {i+1}",
                "latitude": 12.9716 + 0.01 * i,
                "longitude": 77.5946 + 0.01 * i,
                "elevation": 5.0,
                "country": "India",
                "region": "Karnataka",
                "town": "Bengaluru",
                "status": "NORMAL",
            }
        self.rt.simulation.network = None
        self.rt.simulation.ensure_network()

    def tearDown(self):
        for sid in getattr(self, "all_sids", [self.sid]):
            station_service._stations.pop(sid, None)
            self.rt.processor.health.pop(sid, None)
        set_runtime(None)
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_1_injection_acknowledgement_is_immediate(self):
        """Acknowledgement occurs immediately (<300ms) with assigned injection_id and active state."""
        t_start = time.perf_counter()
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="spike",
            parameter="temperature",
            severity="high",
            duration_s=15 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)
        latency_ms = (time.perf_counter() - t_start) * 1000

        self.assertLess(latency_ms, 300, f"Acknowledgement took {latency_ms:.2f}ms, target is <300ms")
        self.assertIsNotNone(f.fault_id)
        self.assertEqual(f.state, "ACTIVE")
        self.assertEqual(f.station_id, self.sid)

    def test_2_station_marked_simulated_fault_active_immediately(self):
        """Station health and broadcast events reflect simulated_fault_active immediately."""
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="spike",
            parameter="temperature",
            severity="high",
            duration_s=15 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)

        health = self.rt.processor.health[self.sid]
        self.assertTrue(health["simulated_fault_active"])
        self.assertEqual(health["injected_fault"]["fault_id"], f.fault_id)

        recent_events = self.rt.broker.recent(50)
        event_types = [e["type"] for e in recent_events]
        self.assertIn(ev.FAULT_INJECTED, event_types)
        self.assertIn(ev.STATION_UPDATED, event_types)

        # Ensure station payload exported to live map has simulated_fault_active
        payload = self.rt.processor.station_event_payload(self.rt.processor.health[self.sid])
        self.assertTrue(payload["simulated_fault_active"])

    def test_3_and_4_prompt_targeted_evaluation_and_genuine_detection(self):
        """Targeted evaluation runs promptly and genuinely detects spike without waiting for 600s cycle."""
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="spike",
            parameter="temperature",
            severity="high",
            duration_s=15 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)

        # Baseline readings for cluster
        now = datetime.now(UTC)
        self.rt.process_now([
            ObservationIn(
                station_id=sid,
                observed_at=now,
                source="SIMULATED_FEED",
                temperature=25.0,
                humidity=60.0,
                pressure=1010.0,
                wind_speed=3.0,
            )
            for sid in self.all_sids
        ])

        # Run prompt targeted evaluation for the injected fault
        t_start = time.perf_counter()
        asyncio.run(self.rt.evaluate_simulated_fault(f))
        detection_duration_ms = (time.perf_counter() - t_start) * 1000

        # Targeted evaluation should complete rapidly (<500ms)
        self.assertLess(detection_duration_ms, 500, f"Targeted evaluation took {detection_duration_ms:.2f}ms")

        health = self.rt.processor.health[self.sid]
        self.assertTrue(health["simulated_fault_active"])
        self.assertEqual(health["fault_detection_status"], "detected")
        self.assertEqual(health["overall_status"], "anomaly")

    def test_5_incident_has_live_fault_injection_provenance(self):
        """Confirmed simulated anomaly creates incident with origin 'Live Fault Injection' and injection_id."""
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="spike",
            parameter="temperature",
            severity="high",
            duration_s=15 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)
        asyncio.run(self.rt.evaluate_simulated_fault(f))

        incs = incident_service.list_all(source="SIMULATED_FEED", station_id=self.sid)
        self.assertGreater(len(incs), 0, "Expected an incident to be opened for confirmed spike")
        inc = incs[0]

        # Verify incident provenance linking
        self.assertEqual(inc["incident_origin"], "Live Fault Injection")
        self.assertEqual(inc["fault_injection_id"], f.fault_id)

        # Verify lifecycle / timeline carries simulation origin
        detail = incident_service.get(inc["incident_id"])
        self.assertIsNotNone(detail)
        lifecycle = incident_service.build_lifecycle(detail)
        timeline_stages = [item["stage"] for item in lifecycle]
        self.assertIn("SIMULATION_INITIATED", timeline_stages)

    def test_6_no_incident_fabricated_when_not_detected(self):
        """Simulation active does not fabricate an incident when observation is nominal or not detected."""
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="drift",  # subtle drift on first step does not trigger an instant alarm
            parameter="temperature",
            severity="low",
            duration_s=60 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)

        # Nominal evaluation with cluster neighbors present
        now = datetime.now(UTC)
        self.rt.process_now([
            ObservationIn(
                station_id=sid,
                observed_at=now,
                source="SIMULATED_FEED",
                temperature=24.0,
                humidity=55.0,
                pressure=1012.0,
                wind_speed=3.0,
                wind_direction=180.0,
                rainfall=0.0,
                dew_point=14.5,
            )
            for sid in self.all_sids
        ])

        incs = incident_service.list_all(source="SIMULATED_FEED", station_id=self.sid)
        self.assertEqual(len(incs), 0, "Nominal reading should not fabricate an incident")

    def test_7_no_duplicate_incidents_on_repeated_observations(self):
        """Repeated observations of the same active fault maintain single deduplicated incident."""
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="spike",
            parameter="temperature",
            severity="high",
            duration_s=15 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)

        # Trigger twice
        asyncio.run(self.rt.evaluate_simulated_fault(f))
        asyncio.run(self.rt.evaluate_simulated_fault(f))

        incs = incident_service.list_all(source="SIMULATED_FEED", station_id=self.sid)
        open_incs = [i for i in incs if i["status"] != "RESOLVED"]
        self.assertEqual(len(open_incs), 1, "Should deduplicate and keep exactly 1 open incident")

    def test_8_simulation_expiry_and_state_cleanup(self):
        """Expiring or clearing a fault cleans up simulated_fault_active state and publishes FAULT_CLEARED."""
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="spike",
            parameter="temperature",
            severity="high",
            duration_s=15 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)
        self.assertTrue(self.rt.processor.health[self.sid]["simulated_fault_active"])

        # Clear fault
        self.rt.faults.cancel(f.fault_id)
        self.rt.clear_active_fault(f)

        health = self.rt.processor.health[self.sid]
        self.assertFalse(health["simulated_fault_active"])
        self.assertIsNone(health.get("injected_fault"))

        recent_events = self.rt.broker.recent(50)
        event_types = [e["type"] for e in recent_events]
        self.assertIn(ev.FAULT_CLEARED, event_types)

    def test_9_operational_telemetry_isolation(self):
        """Simulated fault injection never modifies real station source or operational data."""
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="spike",
            parameter="temperature",
            severity="high",
            duration_s=15 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)

        # Operational reading from physical station
        self.rt.process_now([ObservationIn(
            station_id=self.sid,
            observed_at=datetime.now(UTC),
            source="AWS_IN_SITU",
            temperature=22.0,
            humidity=50.0,
            pressure=1013.0,
        )])

        # Operational incidents must be empty (spike was simulated feed only)
        op_incs = incident_service.list_all(source="LIVE_AWS", station_id=self.sid)
        self.assertEqual(len(op_incs), 0, "Operational telemetry should not be contaminated")

    def test_10_network_state_recovery_after_reconnect(self):
        """GET /api/network/state snapshot correctly preserves active simulation metadata."""
        f = self.rt.faults.inject(
            station_id=self.sid,
            fault_type="spike",
            parameter="temperature",
            severity="high",
            duration_s=15 * 60,
        )
        self.rt.register_active_fault(f, self.stn_dict)

        # Build snapshot
        snap = self.rt.network_snapshot()
        station_entry = next((s for s in snap["stations"] if s["station_id"] == self.sid), None)
        self.assertIsNotNone(station_entry)
        self.assertTrue(station_entry["simulated_fault_active"])
        self.assertIsNotNone(station_entry["injected_fault"])


if __name__ == "__main__":
    unittest.main()
