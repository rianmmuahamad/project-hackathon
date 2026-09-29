import { useEffect, useState } from "react";

import { api } from "../api";
import { relative, severityTone } from "../format";
import type { Notification } from "../types";

/**
 * The audit log of the agent's own judgement calls.
 *
 * Only status changes produce a row: a check that concludes "nothing changed"
 * is the product working, and it stays silent on purpose.
 */
export function NotificationsPage({
  refreshToken,
  onChanged,
}: {
  refreshToken: number;
  onChanged: () => void;
}) {
  const [rows, setRows] = useState<Notification[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .notifications()
      .then((payload) => {
        setRows(payload.notifications);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [refreshToken]);

  async function markRead() {
    try {
      await api.markRead();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const unread = rows.filter((row) => !row.read).length;

  return (
    <>
      <section className="qhead">
        <div className="qhead-top">
          <h1 className="headline">Notifications</h1>
          <span className="qhead-count micro muted">
            {unread ? `${unread} unread` : "All read"} · only status changes appear here
          </span>
          <span className="spacer" />
          <button className="btn btn-secondary" onClick={() => void markRead()} disabled={unread === 0}>
            Mark all read
          </button>
        </div>
        {error && <div className="banner banner-bad">{error}</div>}
      </section>

      <section className="section" style={{ marginTop: "var(--s-xl)" }}>
        {rows.length === 0 ? (
          <div className="card">
            <p className="empty">
              No status changes yet. Checks ending in &ldquo;nothing changed&rdquo; stay quiet on purpose —
              that is the product working, not a failure.
            </p>
          </div>
        ) : (
          <div className="list">
            {rows.map((row) => (
              <a
                className="rowcard rowcard-tight"
                key={row.id}
                href={`#/thesis/${row.thesis_id}`}
                style={row.read ? { background: "var(--canvas)", borderColor: "var(--hair-soft)" } : undefined}
              >
                <div className="rowcard-top">
                  <span className="chip">
                    <i className={`dot dot-${severityTone(row.severity)}`} />
                    {(row.severity || "").toUpperCase()}
                  </span>
                  <span className="rowcard-sym">{row.symbol}</span>
                  <span className="spacer" />
                  <span className="rowcard-conf" title={row.created_at}>
                    {relative(row.created_at)}
                  </span>
                </div>
                <p
                  className="rowcard-stmt"
                  style={{ marginTop: 8, ...(row.read ? { color: "var(--ink-muted)" } : {}) }}
                >
                  {row.title}
                </p>
                <div className="rowcard-delta">{row.body}</div>
              </a>
            ))}
          </div>
        )}
      </section>
    </>
  );
}