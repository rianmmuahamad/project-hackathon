import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { LiveJob } from "./components/LiveJob";
import { ComposePage } from "./pages/ComposePage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { QueuePage } from "./pages/QueuePage";
import { ThesisWorkspace } from "./pages/ThesisWorkspace";
import type { Job, QueueRow, Stats } from "./types";

type View = { name: "queue" } | { name: "thesis"; id: string } | { name: "new" } | { name: "notifications" };

function parseHash(): View {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const [head, id] = hash.split("/");
  if (head === "thesis" && id) return { name: "thesis", id: decodeURIComponent(id) };
  if (head === "new") return { name: "new" };
  if (head === "notifications") return { name: "notifications" };
  return { name: "queue" };
}

const HREF: Record<View["name"], string> = {
  queue: "#/queue",
  thesis: "#/thesis",
  new: "#/new",
  notifications: "#/notifications",
};

export function App() {
  const [view, setView] = useState<View>(parseHash);
  const [stats, setStats] = useState<Stats | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [fatal, setFatal] = useState<string | null>(null);

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
    const onHash = () => setView(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshToken, view]);

  const bump = useCallback(() => setRefreshToken((n) => n + 1), []);

  useEffect(() => {
    if (job?.state !== "running") return;
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [job?.state, refresh]);

  const engine = stats?.engine ?? {};
  const live = Object.entries(engine).find(([, info]) => info.available)?.[0] ?? "none";

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          Thesis Radar<span>does the thesis still hold?</span>
        </div>
        <nav>
          <a href={HREF.queue} className={view.name === "queue" ? "active" : ""}>
            Antrian
          </a>
          <a href={HREF.new} className={view.name === "new" ? "active" : ""}>
            Tesis baru
          </a>
          <a href={HREF.notifications} className={view.name === "notifications" ? "active" : ""}>
            Notifikasi
            {stats && stats.store.unread > 0 && <span className="chip unknown" style={{ marginLeft: 6 }}>{stats.store.unread}</span>}
          </a>
        </nav>
        <span className="spacer" />
        <div className="meta">
          <span title="reasoning engine driving the loop">
            engine <strong>{live}</strong>
          </span>
          <span title="TypeSafe System One decides each claim from measured evidence">
            jev{" "}
            <strong>
              {stats?.jev?.available ? (stats.jev.model ?? "on") : "off"}
            </strong>
          </span>
          <span title="Sectors API credits spent across every call this project has made">
            {stats ? `${stats.credits.credits_spent} credits` : "—"}
          </span>
          <span title="checks run">
            {stats ? `${stats.store.checks} checks` : "—"}
          </span>
        </div>
      </header>

      {fatal && (
        <div className="banner bad" style={{ margin: 0, borderRadius: 0 }}>
          {fatal}
        </div>
      )}

      <div className={`body${view.name === "thesis" ? "" : " solo"}`}>
        {view.name === "thesis" && (
          <aside className="rail">
            <div className="rail-head">
              <span>theses</span>
              <button onClick={() => void api.checkAll({}).then(bump)} disabled={job?.state === "running"}>
                check all
              </button>
            </div>
            <Rail onNavigate={bump} refreshToken={refreshToken} selectedId={view.id} />
          </aside>
        )}

        <main className={view.name === "thesis" ? "" : "wide"}>
          {view.name === "queue" && <QueuePage refreshToken={refreshToken} onChanged={bump} job={job} />}
          {view.name === "new" && <ComposePage onCreated={(id) => (window.location.hash = `#/thesis/${id}`)} />}
          {view.name === "notifications" && <NotificationsPage refreshToken={refreshToken} onChanged={bump} />}
          {view.name === "thesis" && (
            <ThesisWorkspace id={view.id} refreshToken={refreshToken} onChanged={bump} job={job} />
          )}
        </main>
      </div>

      <div style={{ borderTop: "1px solid var(--line)" }}>
        <LiveJob job={job} onFinished={bump} />
      </div>
    </div>
  );
}

function Rail({ selectedId, refreshToken, onNavigate }: { selectedId: string; refreshToken: number; onNavigate: () => void }) {
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

  if (error) return <div className="rail-item error">{error}</div>;
  if (!rows.length) return <div className="rail-item dim">no theses yet</div>;

  return (
    <>
      {rows.map((row) => (
        <a
          key={row.id}
          href={`#/thesis/${row.id}`}
          className={`rail-item${row.id === selectedId ? " selected" : ""}`}
          onClick={onNavigate}
        >
          <div className="row1">
            <span className={`chip ${row.status}`}>{row.status === "needs_review" ? "REVIEW" : row.status.toUpperCase()}</span>
            <span className="sym">{row.symbol}</span>
            <span className="grow" />
            <span className="dim mono">{row.confidence === null ? "" : row.confidence.toFixed(2)}</span>
          </div>
          {row.changes.length > 0 && <div className="change">↳ {row.changes[0].text.slice(0, 120)}</div>}
          {row.changes.length === 0 && <div className="change dim">{row.claims} claim(s) · never checked</div>}
        </a>
      ))}
    </>
  );
}