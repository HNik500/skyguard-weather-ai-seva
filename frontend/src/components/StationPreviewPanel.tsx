import React, { useMemo } from 'react';
import { ArrowRight, X } from 'lucide-react';
import { Station } from '../types/weather';
import { formatAge, INTERPRETATION_LABEL, useLive } from '../services/live';
import { SourceBadge, StatusPill, fmt, pct } from './live/LiveBits';
import { CONFIDENCE_NOTE } from '../utils/pipeline';

interface StationPreviewPanelProps {
  station: Station;
  onClose: () => void;
  onViewDetails: (stationId: string) => void;
  onOpenIncident?: (incidentId: string) => void;
  onOpenTestLab?: () => void;
}

/**
 * Map quick view: enough to decide whether to open the station — identity,
 * current state, what SkyGuard AI found, and the values it found it on. Read-only;
 * everything comes from the live pipeline store (or the catalogue, labelled).
 */
export const StationPreviewPanel: React.FC<StationPreviewPanelProps> = ({
  station,
  onClose,
  onViewDetails,
  onOpenIncident,
  onOpenTestLab,
}) => {
  const { stations, stationsVersion } = useLive();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const live = useMemo(() => stations.get(station.id), [stations, stationsVersion, station.id]);
  const v = live?.values;
  const values: [string, number | null | undefined, number, string][] = [
    ['Temperature', v ? v.temperature : station.temperature, 1, ' °C'],
    ['Humidity', v ? v.humidity : station.humidity, 0, ' %'],
    ['Pressure', v ? v.pressure : station.pressure, 1, ' hPa'],
    ['Wind', v ? v.wind_speed : station.windSpeed, 1, ' km/h'],
  ];
  const location = station.town && station.region && String(station.town).includes(station.region)
    ? station.town : [station.town, station.region].filter(Boolean).join(' · ');

  const isSimActive = Boolean(live?.simulated_fault_active || live?.injected_fault);

  return (
    <section className="lv-card" style={{ flex: 1, minHeight: 0 }}>
      <header className="lv-card-head" style={{ alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <div className="a-eyebrow">{station.id}</div>
          <div style={{ fontWeight: 800, fontSize: '1.02rem', marginTop: 2 }}>{station.name}</div>
          <div className="lv-muted">{location || '—'} · {station.latitude?.toFixed(3)}°, {station.longitude?.toFixed(3)}°</div>
        </div>
        <button className="lv-btn" style={{ padding: 6 }} onClick={onClose} aria-label="Close"><X size={14} /></button>
      </header>
      <div className="lv-card-body" style={{ display: 'flex', flexDirection: 'column', gap: 12, overflowY: 'auto', flex: 1 }}>
        {live ? (
          <>
            <div className="lv-row" style={{ flexWrap: 'wrap', gap: 6 }}>
              <StatusPill status={live.overall_status} watch={live.watch} />
              {isSimActive && (
                <span
                  className="lv-pill"
                  style={{
                    background: 'rgba(168, 85, 247, 0.15)',
                    color: '#c084fc',
                    border: '1px solid rgba(168, 85, 247, 0.4)',
                    fontWeight: 700,
                  }}
                >
                  SIMULATION ACTIVE
                </span>
              )}
              {live.interpretation && live.interpretation !== 'nominal' && (
                <span className={`lv-pill ${live.interpretation === 'likely_weather_event' ? 'lv-status-weather' : 'lv-status-unknown'}`}>{INTERPRETATION_LABEL[live.interpretation]}</span>
              )}
              <SourceBadge source={live.source} simulated={live.simulated} />
            </div>

            {/* Live Fault Injection Card */}
            {isSimActive && (
              <div
                style={{
                  background: 'rgba(168, 85, 247, 0.08)',
                  border: '1px solid rgba(168, 85, 247, 0.35)',
                  borderRadius: 8,
                  padding: '10px 12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span
                      style={{
                        fontSize: '0.68rem',
                        fontWeight: 800,
                        letterSpacing: '0.05em',
                        color: '#c084fc',
                        background: 'rgba(168, 85, 247, 0.2)',
                        padding: '2px 6px',
                        borderRadius: 4,
                        border: '1px solid rgba(168, 85, 247, 0.4)',
                      }}
                    >
                      LIVE FAULT INJECTION
                    </span>
                    <span style={{ fontSize: '0.72rem', color: 'var(--a-ink-3)', fontFamily: 'var(--font-mono)' }}>
                      {live.injected_fault?.injection_id || live.injected_fault?.fault_id || 'ACTIVE'}
                    </span>
                  </div>
                  <span
                    className={`lv-pill lv-pill-sm ${
                      live.fault_detection_status === 'detected'
                        ? 'lv-status-anomaly'
                        : live.fault_detection_status === 'not_detected'
                        ? 'lv-status-nominal'
                        : 'lv-status-suspect'
                    }`}
                  >
                    {live.fault_detection_status === 'detected'
                      ? 'Detected'
                      : live.fault_detection_status === 'not_detected'
                      ? 'Not Detected'
                      : 'Simulation Active'}
                  </span>
                </div>

                <div className="lv-kv" style={{ fontSize: '0.78rem', margin: 0 }}>
                  <dt>Injected fault</dt>
                  <dd>{live.injected_fault?.label || live.injected_fault?.fault_type || 'Custom fault'}</dd>
                  <dt>Affected parameter</dt>
                  <dd>{live.injected_fault?.parameter || 'All sensors'}</dd>
                  <dt>Severity & duration</dt>
                  <dd>
                    {live.injected_fault?.severity || 'medium'} · {live.injected_fault?.duration_minutes || 10} min
                  </dd>
                  <dt>Injected at</dt>
                  <dd>{formatAge(live.injected_fault?.started_at_iso || live.injected_fault?.started_at)}</dd>
                  <dt>Detection state</dt>
                  <dd>
                    {live.overall_status === 'anomaly' && live.fault_detection_status === 'detected' ? (
                      <span style={{ color: '#ef4444', fontWeight: 700 }}>
                        Confirmed Anomaly ({formatAge(live.last_processed_at || live.last_observed_at)})
                      </span>
                    ) : (
                      <span style={{ color: '#c084fc', fontWeight: 600 }}>
                        {live.fault_detection_status === 'not_detected'
                          ? 'Evaluated — Within Normal Bounds'
                          : 'Evaluating via Anomaly Detection Engine…'}
                      </span>
                    )}
                  </dd>
                  {live.active_incident_id && (
                    <>
                      <dt>Incident report</dt>
                      <dd>
                        {onOpenIncident ? (
                          <button
                            className="lv-link"
                            onClick={() => onOpenIncident(live.active_incident_id!)}
                            style={{ fontWeight: 700, color: '#c084fc' }}
                          >
                            {live.active_incident_id}
                          </button>
                        ) : (
                          <span className="lv-mono">{live.active_incident_id}</span>
                        )}
                      </dd>
                    </>
                  )}
                </div>
              </div>
            )}

            <p style={{ margin: 0, fontSize: '0.82rem', lineHeight: 1.5 }}>{live.summary}</p>
            <div className="lv-kv">
              <dt>Evidence from</dt><dd>{live.triggered_layers?.length ? live.triggered_layers.join(', ') : 'no layer'}</dd>
              <dt>Confidence*</dt><dd>{pct(live.confidence)}</dd>
              <dt>Observed</dt><dd>{formatAge(live.last_observed_at)}{live.freshness === 'STALE' ? ' — stale' : ''}</dd>
            </div>
          </>
        ) : (
          <div className="lv-callout info">Not monitored live. Values below come from the static catalogue snapshot and are not evaluated continuously.</div>
        )}
        <div className="lv-stats" style={{ gridTemplateColumns: '1fr 1fr' }}>
          {values.map(([l, val, d, u]) => (
            <div key={l} className="lv-stat"><span className="lv-stat-lbl">{l}</span><span className="lv-stat-val" style={{ fontSize: '1.1rem' }}>{typeof val === 'number' ? fmt(val, d, u) : '—'}</span></div>
          ))}
        </div>
        {live && <p className="a-note" style={{ margin: 0 }}>* {CONFIDENCE_NOTE}</p>}
        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <button className="lv-btn lv-btn-primary" onClick={() => onViewDetails(station.id)}>Open station <ArrowRight size={14} /></button>
          {isSimActive && onOpenTestLab && (
            <button className="lv-btn" onClick={onOpenTestLab}>View in Test Lab</button>
          )}
        </div>
      </div>
    </section>
  );
};
