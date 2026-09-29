import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { LiveJob } from "./components/LiveJob";
import { ComposePage } from "./pages/ComposePage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { QueuePage } from "./pages/QueuePage";
import { ThesisWorkspace } from "./pages/ThesisWorkspace";
import { STATUS_LABEL } from "./format";
import type { Job, QueueRow, Stats } from "./types";

type View = { name: "queue" } | { name: "thesis"; id: string } | { name: "new" } | { name: "notifications" };

const NAV: Array<[View["name"], string]> = [
  ["queue", "Queue"],
  ["new", "New thesis"],
  ["notifications", "Notifications"],
];

function parseHash(): View {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const [head, id] = hash.split("/");
  if (head === "thesis" && id) return { name: "thesis", id: decodeURIComponent(id) };
  if (head === "new") return { name: "new" };
  if (head === "notifications") return { name: "notifications" };
  return { name: "queue" };
}

export function App() {
  const [view, setView] = useState<View>(parseHash);
  const [stats, setStats] = useState<Stats | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [fatal, setFatal] = useState<string | null>(null);
  const [dock, setDock] = useState(true);
  const [rail, setRail] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [nextStats, nextJob] = await Promise.all([api.stats(), api.job()]);
      setStats(nextStats);
      setJob(nextJob.job);
      setFatal(null);
    } catch (error) {
      setFatal(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    const onHash = () => {
      setView(parseHash());
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshToken, view]);

  const bump = useCallback(() => setRefreshToken((n) => n + 1), []);

  const [checkBusy, setCheckBusy] = useState(false);
  async function checkAll() {
    setCheckBusy(true);
    try {
      await api.checkAll({});
      bump();
    } catch (error) {
      setFatal(error instanceof Error ? error.message : String(error));
    } finally {
      setCheckBusy(false);
    }
  }

  useEffect(() => {
    if (job?.state !== "running") return;
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [job?.state, refresh]);

  const running = job?.state === "running";
  const engine = stats?.engine ?? {};
  const engineName = Object.entries(engine).find(([, info]) => info.available)?.[0] ?? "none";
  const jev = stats?.jev;
  const unread = stats?.store.unread ?? 0;
  const withRail = view.name === "thesis";

  return (
    <div className="app">
      <header className="topnav">
        <div className="topnav-left">
          <a className="brand" href="#/queue">
            <span className="brand-mark">Thesis Radar</span>
            <span className="brand-sub">does the thesis still hold?</span>
          </a>
        </div>

        <nav className="navpills" aria-label="primary">
          {NAV.map(([name, label]) => (
            <a key={name} href={`#/${name}`} className={`navpill${view.name === name ? " on" : ""}`}>
              {label}
              {name === "notifications" && unread > 0 && <b className="navcount">{unread}</b>}
            </a>
          ))}
        </nav>

        <div className="topnav-right">
          {!dock && (
            <button className="dock-peek" onClick={() => setDock(true)} title="Show agent log">
              {running ? <i className="pulse" /> : <i className="dot dot-unknown" />}
              <span>{running ? "running" : "idle"}</span>
            </button>
          )}
          <div className="navcta">
            <button className="btn btn-primary" onClick={() => void checkAll()} disabled={checkBusy || running}>
              {running ? "Running..." : "Check all"}
            </button>
          </div>
          {dock && (
            <button
              className="btn btn-secondary btn-icon dock-toggle"
              aria-label="Agent log"
              aria-expanded={dock}
              onClick={() => setDock(false)}
            >
              {running ? <i className="pulse" /> : <i className="dot dot-unknown" />}
            </button>
          )}
        </div>
      </header>

      {fatal && (
        <div className="banner banner-bad" style={{ margin: "12px 20px" }}>
          {fatal}
        </div>
      )}

      <div
        className={`work${withRail ? " with-rail" : ""}${withRail && !rail ? " rail-hidden" : ""}${dock ? "" : " dock-hidden"}`}
      >
        {withRail && <Rail selectedId={view.id} refreshToken={refreshToken} collapsed={!rail} onToggle={() => setRail(!rail)} />}

        <main className="main">
          <div className="main-inner">
            {view.name === "queue" && (
              <QueuePage refreshToken={refreshToken} onChanged={bump} job={job} stats={stats} />
            )}
            {view.name === "new" && <ComposePage onCreated={(id) => (window.location.hash = `#/thesis/${id}`)} />}
            {view.name === "notifications" && <NotificationsPage refreshToken={refreshToken} onChanged={bump} />}
            {view.name === "thesis" && (
              <ThesisWorkspace id={view.id} refreshToken={refreshToken} onChanged={bump} job={job} />
            )}
            <footer className="foot">
              <div className="foot-grid">
                <div>
                  <div className="foot-brand">
                    Thesis Radar<span>does the thesis still hold?</span>
                  </div>
                </div>
                <div className="foot-cols">
                  <div>
                    <span className="foot-h">Routes</span>
                    <a href="#/queue">Queue</a>
                    <a href="#/new">New thesis</a>
                    <a href="#/notifications">Notifications</a>
                  </div>
                  <div>
                    <span className="foot-h">Machine</span>
                    <span>{engineName}</span>
                    <span>jev {jev?.available ? (jev.model ?? "on") : "off"}</span>
                  </div>
                  <div>
                    <span className="foot-h">Data</span>
                    <span>{stats ? `${stats.store.theses} theses` : "—"}</span>
                    <span>{stats ? `${stats.store.checks} checks` : "—"}</span>
                    <span>{stats ? `${stats.credits.credits_spent} credits` : "—"}</span>
                  </div>
                </div>
              </div>
              <p className="foot-note">
                Numbers are computed in code, judgment is by the agent. A monitor of investment reasoning,
                not investment advice.
              </p>
            </footer>
          </div>
        </main>

        {dock && <LiveJob job={job} onFinished={bump} />}
      </div>

      <BottomBar current={view.name} unread={unread} />
    </div>
  );
}

/**
 * The primary navigation on a phone: the same pill group, moved to the bottom.
 *
 * The markup is the top bar's own — `.navpills` wrapping `.navpill` — so the
 * shape is identical at both widths. Only the position changes, via CSS: below
 * 900px `.navpills` inside `.bottombar` is `position: fixed; bottom: 0`. The
 * same node is never rendered twice, so there is one nav in the accessibility
 * tree at any width.
 */
function BottomBar({ current, unread }: { current: View["name"]; unread: number }) {
  return (
    <div className="bottombar">
      <nav className="navpills" aria-label="primary mobile">
        {NAV.map(([name, label]) => (
          <a key={name} href={`#/${name}`} className={`navpill${current === name ? " on" : ""}`}>
            {label}
            {name === "notifications" && unread > 0 && <b className="navcount">{unread}</b>}
          </a>
        ))}
      </nav>
    </div>
  );
}

function Rail({
  selectedId,
  refreshToken,
  collapsed,
  onToggle,
}: {
  selectedId: string;
  refreshToken: number;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const [rows, setRows] = useState<QueueRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .queue()
      .then((payload) => {
        setRows(payload.theses);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [refreshToken]);

  if (collapsed) {
    return (
      <aside className="rail rail-collapsed" aria-label="thesis list, collapsed">
        <div className="rail-head rail-head-strip">
          <button className="btn btn-ghost btn-icon rail-edge" onClick={onToggle} aria-expanded={false} title="Expand">
            ›
          </button>
        </div>
        {rows.length ? (
          rows.map((row) => (
            <a
              key={row.id}
              href={`#/thesis/${row.id}`}
              className={`rail-strip-item${row.id === selectedId ? " selected" : ""}`}
              title={row.company_name ? `${row.symbol} — ${row.company_name}` : row.symbol}
            >
              <i className={`dot dot-${row.status}`} />
              <span className="rail-strip-sym">{row.symbol}</span>
            </a>
          ))
        ) : (
          <div className="rail-empty">—</div>
        )}
      </aside>
    );
  }

  return (
    <aside className="rail" aria-label="thesis list">
      <div className="rail-head">
        <button className="btn btn-ghost btn-icon rail-edge" onClick={onToggle} aria-expanded title="Collapse">
          ‹
        </button>
        <span className="eyebrow">Theses</span>
      </div>
      {error && <div className="rail-empty">{error}</div>}
      {!error && !rows.length && <div className="rail-empty">no theses yet</div>}
      {rows.map((row) => (
        <a
          key={row.id}
          href={`#/thesis/${row.id}`}
          className={`rail-item${row.id === selectedId ? " selected" : ""}`}
        >
          <div className="pillrow" style={{ gap: 10 }}>
            <span className="chip">
              <i className={`dot dot-${row.status}`} />
              {STATUS_LABEL[row.status]}
            </span>
            <span className="rail-sym">{row.symbol}</span>
            <span className="spacer" />
            <span className="mono muted">{row.confidence === null ? "" : row.confidence.toFixed(2)}</span>
          </div>
          <div className="rail-note">
            {row.changes.length
              ? `↳ ${row.changes[0].text.slice(0, 120)}`
              : `${row.claims} claim(s) · never checked`}
          </div>
        </a>
      ))}
    </aside>
  );
}