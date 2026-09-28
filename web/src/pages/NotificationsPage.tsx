import { useEffect, useState } from "react";

import { api } from "../api";
import { relative } from "../format";
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

  return (
    <>
      <h1>Notifikasi</h1>
      <p className="lead">
        Hanya perubahan status yang muncul di sini. Pemeriksaan yang berakhir &ldquo;tidak ada yang
        berubah&rdquo; sengaja tidak memberi kabar — itu produknya bekerja, bukan kegagalan.
      </p>

      {error && <div className="banner bad">{error}</div>}

      <div className="row" style={{ marginBottom: 12 }}>
        <button onClick={() => void markRead()}>tandai semua dibaca</button>
        <span className="sub">{rows.filter((row) => !row.read).length} belum dibaca</span>
      </div>

      {rows.length === 0 ? (
        <div className="empty">Belum ada perubahan status.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th style={{ width: 92 }}>Saham</th>
              <th style={{ width: 90 }}>Tingkat</th>
              <th>Perubahan</th>
              <th style={{ width: 110 }}>Kapan</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                style={{ cursor: "pointer", opacity: row.read ? 0.6 : 1 }}
                onClick={() => (window.location.hash = `#/thesis/${row.thesis_id}`)}
              >
                <td className="mono">{row.symbol}</td>
                <td>
                  <span className={`chip ${severityTone(row.severity)}`}>{row.severity}</span>
                </td>
                <td>
                  <strong>{row.title}</strong>
                  <div className="dim">{row.body}</div>
                </td>
                <td className="mono dim">{relative(row.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function severityTone(severity: string): string {
  if (severity === "alert") return "broken";
  if (severity === "warning") return "weakened";
  if (severity === "ok") return "intact";
  return "unknown";
}