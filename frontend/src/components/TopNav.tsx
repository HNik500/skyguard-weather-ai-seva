import React, { useEffect, useRef, useState } from 'react';
import { Search, Menu, X, ShieldAlert, Cpu } from 'lucide-react';
import { Station } from '../types/weather';
import { searchStations } from '../services/api';
import { Workspace } from '../types/workspace';
import { useLive } from '../services/live';

interface TopNavProps {
  activeWorkspace: Workspace;
  onNavigate: (workspace: Workspace) => void;
  onSelectStation: (stationId: string) => void;
}

/** The five product destinations. Station detail and System are reached
 *  from inside the product (a station, the live indicator), not as tabs. */
const TABS: { id: Workspace; label: string; also?: Workspace[] }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'map', label: 'Live Map', also: ['station'] },
  { id: 'incidents', label: 'Incidents' },
  { id: 'anomalies', label: 'Investigations' },
  { id: 'testlab', label: 'Test Lab' },
];

export const TopNav: React.FC<TopNavProps> = ({ activeWorkspace, onNavigate, onSelectStation }) => {
  const { connection, lastEventAt, incidentCounts, system } = useLive();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Station[]>([]);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const mobileDrawerRef = useRef<HTMLDivElement>(null);
  const mobileSearchRef = useRef<HTMLDivElement>(null);

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (!q.trim()) { setResults([]); setOpen(false); return; }
    const t = setTimeout(() => searchStations(q).then((r) => { setResults(r); setOpen(r.length > 0); }).catch(() => {}), 150);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      const target = e.target as Node;
      if (boxRef.current && !boxRef.current.contains(target)) setOpen(false);
      if (mobileDrawerRef.current && !mobileDrawerRef.current.contains(target)) {
        const toggleBtn = document.querySelector('.a-mobile-menu-btn');
        if (toggleBtn && !toggleBtn.contains(target)) setMobileMenuOpen(false);
      }
      if (mobileSearchRef.current && !mobileSearchRef.current.contains(target)) {
        const searchBtn = document.querySelector('.a-mobile-search-btn');
        if (searchBtn && !searchBtn.contains(target)) setMobileSearchOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        setMobileMenuOpen(false);
        setMobileSearchOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, []);

  const handleNav = (ws: Workspace) => {
    setMobileMenuOpen(false);
    setMobileSearchOpen(false);
    onNavigate(ws);
  };

  const handleSelectStation = (id: string) => {
    setOpen(false);
    setMobileMenuOpen(false);
    setMobileSearchOpen(false);
    setQ('');
    onSelectStation(id);
  };

  // Two separate facts: is the server reachable (SSE heartbeat every 5 s),
  // and is TELEMETRY fresh (age of the newest processed observation vs the
  // source cadence). "LIVE" requires both; a connected server with old data
  // says STALE DATA and how old it is.
  const hbAge = lastEventAt ? Math.round((now - lastEventAt) / 1000) : null;
  const connected = connection === 'live' && hbAge !== null && hbAge < 30;
  const newest = system?.metrics?.newest_observation_epoch as number | null | undefined;
  const cadence = Math.max(60, ...((system?.sources || []).filter((s: any) => s.kind !== 'REFERENCE' && (s.state === 'ACTIVE' || s.state === 'DEGRADED')).map((s: any) => s.cadence_s || 0)));
  const age = newest ? Math.max(0, Math.round(now / 1000 - newest)) : null;
  const fresh = age !== null && age <= 3 * cadence;
  const live = connected && fresh;
  const label = connection === 'offline' ? 'OFFLINE' : connection !== 'live' ? 'CONNECTING' : !connected ? 'NO RECENT DATA' : age === null ? 'NO TELEMETRY' : fresh ? 'LIVE' : 'STALE DATA';
  const ageText = age === null ? '' : age < 120 ? `${age}s` : age < 7200 ? `${Math.round(age / 60)}m` : `${Math.round(age / 3600)}h`;
  const open_ = incidentCounts?.active ?? 0;

  return (
    <>
      <header className="a-nav">
        <button className="a-brand" onClick={() => handleNav('home')} title="SkyGuard AI home">
          <span className="a-brand-mark" />
          <span style={{ textAlign: 'left' }}>
            <span className="a-brand-name">SkyGuard AI</span>
            <span className="a-brand-sub">Weather intelligence</span>
          </span>
        </button>

        <nav className="a-tabs" aria-label="SkyGuard AI navigation">
          {TABS.map((t) => {
            const active = activeWorkspace === t.id || !!t.also?.includes(activeWorkspace);
            return (
              <button key={t.id} className={`a-tab ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined} onClick={() => handleNav(t.id)}>
                {t.label}
                {t.id === 'incidents' && open_ > 0 && <span className="a-tab-count" title="Open incidents">{open_}</span>}
              </button>
            );
          })}
        </nav>

        <div className="a-nav-right">
          <div className="a-search" ref={boxRef}>
            <Search size={14} />
            <input value={q} onChange={(e) => setQ(e.target.value)} onFocus={() => results.length && setOpen(true)}
              placeholder="Find station by name or ID" aria-label="Find station" />
            {open && (
              <div className="a-search-menu">
                {results.map((s) => (
                  <button key={s.id} className="a-search-item" onClick={() => handleSelectStation(s.id)}>
                    <span>
                      <div style={{ fontWeight: 700, fontSize: '0.8rem' }}>{s.name}</div>
                      <div className="lv-mono" style={{ fontSize: '0.66rem', color: 'var(--a-ink-3)' }}>{s.id} · {s.town}</div>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            className="a-mobile-search-btn"
            onClick={() => {
              setMobileSearchOpen((v) => !v);
              if (mobileMenuOpen) setMobileMenuOpen(false);
            }}
            aria-label="Search stations"
            title="Search stations"
          >
            <Search size={16} />
          </button>

          <button
            className="a-live"
            onClick={() => handleNav('system')}
            title="Telemetry freshness = age of the newest processed observation (expected every source cadence). Click for pipeline and data-source health."
          >
            <span className={`lv-live-dot ${live ? '' : connection === 'offline' ? 'off' : 'wait'}`} />
            <span className="a-live-label">{label}</span>
            <span className="a-live-age">{connected && age !== null ? ` · data ${ageText} old` : ''}</span>
          </button>

          <button
            className="a-mobile-menu-btn"
            onClick={() => {
              setMobileMenuOpen((v) => !v);
              if (mobileSearchOpen) setMobileSearchOpen(false);
            }}
            aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileMenuOpen}
            title={mobileMenuOpen ? 'Close navigation' : 'Open navigation'}
          >
            {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </header>

      {/* Mobile Station Search Bar */}
      {mobileSearchOpen && (
        <div className="a-mobile-search-bar" ref={mobileSearchRef}>
          <div className="a-mobile-search-input-wrap">
            <Search size={15} />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search station by name or ID..."
              aria-label="Search station"
              autoFocus
            />
            {q && (
              <button className="a-mobile-search-clear" onClick={() => setQ('')} aria-label="Clear search">
                <X size={14} />
              </button>
            )}
          </div>
          {results.length > 0 && (
            <div className="a-mobile-search-results">
              {results.slice(0, 8).map((s) => (
                <button key={s.id} className="a-search-item" onClick={() => handleSelectStation(s.id)}>
                  <span>
                    <div style={{ fontWeight: 700, fontSize: '0.84rem' }}>{s.name}</div>
                    <div className="lv-mono" style={{ fontSize: '0.68rem', color: 'var(--a-ink-3)' }}>{s.id} · {s.town}</div>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Mobile Navigation Drawer */}
      {mobileMenuOpen && (
        <nav className="a-mobile-drawer" ref={mobileDrawerRef} aria-label="Mobile Navigation">
          <div className="a-mobile-drawer-inner">
            <div className="a-mobile-drawer-links">
              {TABS.map((t) => {
                const active = activeWorkspace === t.id || !!t.also?.includes(activeWorkspace);
                return (
                  <button
                    key={t.id}
                    className={`a-mobile-nav-link ${active ? 'active' : ''}`}
                    onClick={() => handleNav(t.id)}
                    aria-current={active ? 'page' : undefined}
                  >
                    <span className="a-mobile-nav-label">{t.label}</span>
                    {t.id === 'incidents' && open_ > 0 && (
                      <span className="a-tab-count" title="Open incidents">
                        {open_}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            <div className="a-mobile-drawer-footer">
              <button className="a-mobile-sys-link" onClick={() => handleNav('system')}>
                <Cpu size={14} />
                <span>System Health &amp; Pipeline Status</span>
                <span className={`lv-live-dot ${live ? '' : connection === 'offline' ? 'off' : 'wait'}`} />
              </button>
            </div>
          </div>
        </nav>
      )}
    </>
  );
};

