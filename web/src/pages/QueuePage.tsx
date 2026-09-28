import { useEffect, useState } from "react";

import { api } from "../api";
import type { Job, QueueRow } from "../types";
import { relative, shortDate } from "../format";

/**
 * The worklist. Worst first.
 *
 * A user does not start from "run a scan": they start from "which of the things
 * I own no longer make sense?" The queue answers that, and the check-all button
 * is the recurring routine — not a search box.
 */
export function QueuePage({
  refreshToken,
  onChanged,
  job,
}: {
  refreshToken: number;
  onChanged: () => void;
  job: Job | null;
}) {
  const [rows, setRows] = useState<QueueRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .queue()
      .then((payload) => {
        setRows(payload.theses);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [refreshToken]);

  async function checkAll() {
    setBusy(true);
    try {
      await api.checkAll({});
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const running = job?.state === "running";
  const counts = rows.reduce<Record<string, number>>((acc, row) => {
    acc[row.status] = (acc[row.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <h1>Antrian tesis</h1>
      <p className="lead">
        Setiap baris adalah alasan tertulis seseorang memiliki sebuah saham. Agen memeriksa apakah alasannya
        masih berdiri, dan hanya memberi tahu kalau jawabannya berubah.
      </p>

      {error && <div className="banner bad">{error}</div>}

      <div className="row wrap" style={{ marginBottom: 14 }}>
        <button className="primary" onClick={() => void checkAll()} disabled={busy || running}>
          {running ? "sedang berjalan…" : "periksa semua"}
        </button>
        <a href="#/new">
          <button>+ tesis baru</button>
        </a>
        <span className="grow" />
        <span className="sub">
          {(["broken", "weakened", "needs_review", "intact"] as const)
            .filter((status) => counts[status])
            .map((status) => `${counts[status]} ${status}`)
            .join(" · ") || "belum ada tesis"}
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="empty">
          Belum ada tesis. Tulis satu di <a href="#/new">Tesis baru</a> — misalnya
          <em> &ldquo;kredit BBRI tumbuh minimal 10% YoY&rdquo;</em>.
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th style={{ width: 90 }}>Status</th>
              <th style={{ width: 60 }} className="num">
                Conf
              </th>
              <th style={{ width: 78 }}>Saham</th>
              <th>Perubahan terakhir</th>
              <th style={{ width: 92 }} className="num">
                Klaim
              </th>
              <th style={{ width: 120 }}>Diperiksa</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} style={{ cursor: "pointer" }} onClick={() => (window.location.hash = `#/thesis/${row.id}`)}>
                <td>
                  <span className={`chip ${row.status}`}>
                    {row.status === "needs_review" ? "REVIEW" : row.status.toUpperCase()}
                  </span>
                </td>
                <td className="num mono">{row.confidence === null ? "—" : row.confidence.toFixed(2)}</td>
                <td className="mono">{row.symbol}</td>
                <td>
                  {row.changes.length > 0 ? (
                    <>
                      {row.changes[0].text}
                      {row.changes[0].magnitude && <span className="muted"> · {row.changes[0].magnitude}</span>}
                    </>
                  ) : (
                    <span className="dim">{row.last_check?.summary ?? row.statement}</span>
                  )}
                </td>
                <td className="num mono">
                  {row.last_check ? `${row.last_check.tool_calls} tool` : `${row.claims} claim`}
                </td>
                <td className="mono dim" title={row.last_checked_at ?? ""}>
                  {relative(row.last_checked_at)}
                  {row.watermark && <div className="dim">since {shortDate(row.watermark)}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Bagaimana produk ini bekerja</h2>
      <div className="grid2">
        <div className="card tight">
          <h3>Angka dihitung kode, penilaian dilakukan agen</h3>
          <p className="sub" style={{ margin: 0 }}>
            Nilai terbaru, perubahan YoY, dan uji ambang batas dihitung di Python dari data yang sudah
            tersimpan. Tidak ada angka dalam putusan yang diketik model. Agen memakainya untuk menjawab
            pertanyaan yang tidak bisa dihitung: apakah pergerakan ini milik perusahaan atau seluruh pasar,
            apakah harga bergerak karena aksi korporasi, dan apakah alasan yang tertulis masih masuk akal.
          </p>
        </div>
        <div className="card tight">
          <h3>Watermark</h3>
          <p className="sub" style={{ margin: 0 }}>
            Setiap pemeriksaan menyimpan tanggal. Pemeriksaan berikutnya hanya membaca yang baru sejak tanggal
            itu — makanya baris &ldquo;perubahan terakhir&rdquo; di atas ada isinya, dan makanya memeriksa ulang
            hampir tidak memakai kredit.
          </p>
        </div>
      </div>
    </>
  );
}