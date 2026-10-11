"""
Test Suite for SkyGuard AI Monitored Indian AWS Network Scoping
================================================================
Verifies that:
1. The authoritative Indian AWS registry contains exactly the 296 monitored stations from WeatherUnionInfra.csv.
2. Operational incidents for monitored Indian AWS stations appear in the operational queue.
3. Unrelated Slovakian stations (Bytča, Stupava, Brezno, Bratislava) and other foreign stations (Munich, Sydney)
   do NOT appear in the Indian operational incident queue or active counts.
4. Historical foreign records remain queryable under scope="global" for audit/archive purposes without data destruction.
5. Severity, status, and lifecycle transitions work correctly on legitimate Indian incidents.
6. Simulated incidents remain separately identifiable with their SIMULATED provenance.
"""

import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

_TMP_DB = tempfile.NamedTemporaryFile(prefix="ather_test_indian_scope_", suffix=".db", delete=False)
_TMP_DB.close()
os.environ["ATHER_INCIDENTS_DB_PATH"] = _TMP_DB.name

from app.stations.registry import (
    load_monitored_indian_aws_registry,
    get_monitored_indian_aws_ids,
    is_monitored_indian_aws,
    get_monitored_station,
)
from app.incidents import service as incident_service
from app.incidents import db as incident_db


class TestMonitoredIndianAWSRegistry(unittest.TestCase):
    def test_authoritative_registry_station_count(self):
        registry = load_monitored_indian_aws_registry()
        self.assertEqual(len(registry), 296, "Registry must contain exactly 296 monitored Indian AWS stations")

    def test_monitored_ids_match_registry(self):
        ids = get_monitored_indian_aws_ids()
        self.assertEqual(len(ids), 296)
        self.assertIn("ZWL004900", ids, "Rajarajeshwari Nagar AWS must be in monitored IDs")
        self.assertIn("ZWL001472", ids, "Kharadi AWS must be in monitored IDs")

    def test_all_stations_have_valid_indian_coordinates(self):
        registry = load_monitored_indian_aws_registry()
        for sid, stn in registry.items():
            lat = stn["latitude"]
            lon = stn["longitude"]
            self.assertTrue(6.0 <= lat <= 38.0, f"Station {sid} latitude {lat} outside India bounds")
            self.assertTrue(68.0 <= lon <= 98.0, f"Station {sid} longitude {lon} outside India bounds")
            self.assertEqual(stn["country"], "India")
            self.assertTrue("Automated weather system" in stn["device_type"])

    def test_slovakian_and_foreign_stations_rejected_by_scope_rule(self):
        # Slovakian stations from historical global dataset
        slovakian_cases = [
            ("ATHER-SKW-0211", "Bytča", "Slovakia", 49.22, 18.55),
            ("ATHER-SKW-0215", "Stupava", "Slovakia", 48.27, 17.03),
            ("ATHER-SKW-0205", "Bratislava – Dúbravka", "Slovakia", 48.18, 17.03),
            ("ATHER-SKW-0220", "Brezno", "Slovakia", 48.80, 19.64),
        ]
        for sid, name, country, lat, lon in slovakian_cases:
            self.assertFalse(
                is_monitored_indian_aws(sid, country=country, lat=lat, lon=lon),
                f"Slovakian station {name} ({sid}) must NOT be considered a monitored Indian AWS station",
            )

        # Other global stations
        foreign_cases = [
            ("ATHER-EUR-001", "Munich", "Germany", 48.13, 11.58),
            ("ATHER-AUS-001", "Sydney", "Australia", -33.86, 151.20),
            ("ATHER-NAM-0106", "FishRiver Canyon", "Africa", -27.50, 17.50),
        ]
        for sid, name, country, lat, lon in foreign_cases:
            self.assertFalse(
                is_monitored_indian_aws(sid, country=country, lat=lat, lon=lon),
                f"Foreign station {name} ({sid}) must NOT be considered a monitored Indian AWS station",
            )


class TestOperationalIncidentsScoping(unittest.TestCase):
    def setUp(self):
        incident_db.reset_for_tests()

    def test_indian_aws_operational_incident_appears_in_queue(self):
        snapshot = {
            "station_id": "ZWL004900",
            "station_name": "Rajarajeshwari Nagar AWS",
            "town": "Rajarajeshwari Nagar",
            "region": "Karnataka",
            "country": "India",
            "parameter": "Temperature",
            "observed_value": 44.5,
            "expected_min": 20.0,
            "expected_max": 34.0,
            "unit": "°C",
            "status": "ANOMALY",
            "severity": "CRITICAL",
            "anomaly_score": 0.94,
            "confidence": 0.91,
            "root_cause": "SENSOR_SPIKE",
            "source": "LIVE_AWS",
            "evidence": ["Temperature 44.5C exceeds climatological maximum (34.0C)"],
            "diagnostic_layers": {"physics": {"status": "ANOMALY", "score": 0.94}},
        }
        inc = incident_service.upsert_from_evaluation(snapshot)
        self.assertIsNotNone(inc, "Operational incident for monitored Indian AWS should be created")
        self.assertEqual(inc["station_id"], "ZWL004900")
        self.assertEqual(inc["severity"], "CRITICAL")
        self.assertEqual(inc["status"], "NEW")

        # Must appear in default operational queue (scope="india")
        india_queue = incident_service.list_all(source="LIVE_AWS", scope="india")
        self.assertEqual(len(india_queue), 1)
        self.assertEqual(india_queue[0]["station_id"], "ZWL004900")

    def test_slovakian_station_rejected_from_operational_incident_creation(self):
        slovakian_snapshot = {
            "station_id": "ATHER-SKW-0211",
            "station_name": "Bytča AWS",
            "town": "Bytča",
            "region": "Žilina",
            "country": "Slovakia",
            "parameter": "Temperature",
            "observed_value": 41.2,
            "status": "ANOMALY",
            "severity": "CRITICAL",
            "source": "LIVE_AWS",
        }
        inc = incident_service.upsert_from_evaluation(slovakian_snapshot)
        self.assertIsNone(inc, "Foreign station incident must not be created for LIVE_AWS")

        india_queue = incident_service.list_all(source="LIVE_AWS", scope="india")
        self.assertEqual(len(india_queue), 0)

    def test_existing_foreign_records_in_db_excluded_from_india_scope(self):
        conn = incident_db.get_connection()
        # Seed an Indian incident
        conn.execute(
            """INSERT INTO incidents (incident_id, fingerprint, station_id, station_name, country, source, status, severity, created_at, detected_at, first_seen_at, last_seen_at, updated_at)
               VALUES ('INC-IND-01', 'FP1', 'ZWL004900', 'Rajarajeshwari Nagar AWS', 'India', 'LIVE_AWS', 'NEW', 'CRITICAL', '2026-10-11T12:00:00Z', '2026-10-11T12:00:00Z', '2026-10-11T12:00:00Z', '2026-10-11T12:00:00Z', '2026-10-11T12:00:00Z')"""
        )
        # Seed historical foreign incidents (Slovakia, Germany, Australia)
        conn.execute(
            """INSERT INTO incidents (incident_id, fingerprint, station_id, station_name, country, source, status, severity, created_at, detected_at, first_seen_at, last_seen_at, updated_at)
               VALUES ('INC-SK-01', 'FP2', 'ATHER-SKW-0211', 'Bytča AWS', 'Slovakia', 'LIVE_AWS', 'NEW', 'CRITICAL', '2026-09-10T12:00:00Z', '2026-09-10T12:00:00Z', '2026-09-10T12:00:00Z', '2026-09-10T12:00:00Z', '2026-09-10T12:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO incidents (incident_id, fingerprint, station_id, station_name, country, source, status, severity, created_at, detected_at, first_seen_at, last_seen_at, updated_at)
               VALUES ('INC-DE-01', 'FP3', 'ATHER-EUR-001', 'Munich AWS', 'Germany', 'LIVE_AWS', 'WARNING', 'WARNING', '2026-09-10T12:00:00Z', '2026-09-10T12:00:00Z', '2026-09-10T12:00:00Z', '2026-09-10T12:00:00Z', '2026-09-10T12:00:00Z')"""
        )
        conn.commit()

        # Operational India-scoped list must contain ONLY the Indian incident
        india_list = incident_service.list_all(source="LIVE_AWS", scope="india")
        self.assertEqual(len(india_list), 1)
        self.assertEqual(india_list[0]["incident_id"], "INC-IND-01")
        self.assertEqual(india_list[0]["station_id"], "ZWL004900")

        # Active counts must count ONLY the Indian incident
        india_counts = incident_service.get_active_counts(source="LIVE_AWS", scope="india")
        self.assertEqual(india_counts["active"], 1)
        self.assertEqual(india_counts["critical"], 1)

        # Non-destructive historical archive query (scope="global") retains all 3 records for audit
        global_list = incident_service.list_all(source="LIVE_AWS", scope="global")
        self.assertEqual(len(global_list), 3)

        global_counts = incident_service.get_active_counts(source="LIVE_AWS", scope="global")
        self.assertEqual(global_counts["active"], 3)  # All 3 are unclosed (NEW/WARNING)

    def test_simulated_incidents_isolated_with_correct_provenance(self):
        sim_snapshot = {
            "station_id": "ZWL001472",
            "station_name": "Kharadi AWS",
            "country": "India",
            "parameter": "Temperature",
            "observed_value": 52.0,
            "status": "ANOMALY",
            "severity": "CRITICAL",
            "source": "SIMULATED_FEED",
            "provenance": "SIMULATED",
            "context": {"fault_injection_id": "SIM-INJ-999", "incident_origin": "Live Fault Injection"},
        }
        inc = incident_service.upsert_from_evaluation(sim_snapshot)
        self.assertIsNotNone(inc)
        self.assertEqual(inc["source"], "SIMULATED_FEED")
        self.assertEqual(inc["fault_injection_id"], "SIM-INJ-999")

        # Excluded from operational LIVE_AWS list
        op_list = incident_service.list_all(source="LIVE_AWS", scope="india")
        self.assertEqual(len(op_list), 0)

        # Appears in simulated list
        sim_list = incident_service.list_all(source="SIMULATED_FEED", scope="india")
        self.assertEqual(len(sim_list), 1)
        self.assertEqual(sim_list[0]["station_id"], "ZWL001472")
        self.assertEqual(sim_list[0]["incident_origin"], "Live Fault Injection")


if __name__ == "__main__":
    unittest.main()
