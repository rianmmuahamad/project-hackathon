import { useEffect, useState } from "react";

import { api } from "../api";
import type { Decomposition, Draft } from "../types";

/**
 * Writing a thesis down.
 *
 * This screen is where the agent is most visible: a paragraph goes in, and
 * checkable claims come out — with the unverifiable half named rather than
 * dropped. The user confirms or edits before anything is trusted, because a
 * purpose-built interface for this one task is the product, not the model call.
 */
export function ComposePage({ onCreated }: { onCreated: (id: string) => void }) {
  const [symbol, setSymbol] = useState("");
  const [statement, setStatement] = useState("");
  const [horizon, setHorizon] = useState("2 kuartal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; split: Decomposition; credits: number } | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftNote, setDraftNote] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const payload = await api.createThesis({ symbol, statement, horizon });
      setResult({
        id: payload.thesis.id,
        split: payload.decomposition,
        credits: payload.credits,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function suggest() {
    setDraftBusy(true);
    try {
      const payload = await api.draft("banks", 3);
      setDrafts(payload.drafts);
      setDraftNote(`${payload.note} (${payload.credits} credits)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDraftBusy(false);
    }
  }

  useEffect(() => {
    if (result) window.scrollTo({ top: 0 });
  }, [result]);

  if (result) {
    const checkable = result.split.claims.length;
    const unresolved = result.split.unresolved ?? [];
    return (
      <>
        <h1>Tesis tersimpan</h1>
        <p className="lead">
          Dipecah jadi {checkable} klaim yang bisa diperiksa
          {unresolved.length > 0 && `, dan ${unresolved.length} bagian yang tidak bisa diperiksa dengan data ini`}.
        </p>
        <div className="banner info">
          Dipecah oleh <strong>{result.split.mode === "model" ? "model" : "heuristik offline"}</strong> ·{" "}
          {result.credits} credits untuk baseline
        </div>

        {unresolved.length > 0 && (
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Tidak bisa diperiksa</h3>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {unresolved.map((item, index) => (
                <li key={index}>
                  {item.text} — <span className="dim">{item.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="row" style={{ marginTop: 18 }}>
          <button className="primary" onClick={() => onCreated(result.id)}>
            buka berkas tesis
          </button>
          <button
            onClick={() => {
              setResult(null);
              setStatement("");
              setSymbol("");
            }}
          >
            tulis lagi
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <h1>Tesis baru</h1>
      <p className="lead">
        Tulis alasan Anda memiliki sebuah saham dengan bahasa biasa. Agen memecahnya jadi klaim yang bisa
        diperiksa, merekam nilai metriknya sekarang sebagai baseline, dan menandai bagian yang tidak bisa
        diverifikasi.
      </p>

      {error && <div className="banner bad">{error}</div>}

      <div className="grid2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Tesis</h3>
          <div className="col">
            <label>
              <span className="sub">Saham (IDX)</span>
              <input
                value={symbol}
                onChange={(event) => setSymbol(event.target.value.toUpperCase())}
                placeholder="BBRI"
              />
            </label>
            <label>
              <span className="sub">Alasan</span>
              <textarea
                value={statement}
                onChange={(event) => setStatement(event.target.value)}
                placeholder="Beli BBRI karena kredit tumbuh minimal 10% YoY dan pendapatan bunga bersih naik terus, jadi laba masih akan naik dua kuartal ke depan."
              />
            </label>
            <label>
              <span className="sub">Horizon</span>
              <input value={horizon} onChange={(event) => setHorizon(event.target.value)} />
            </label>
            <button
              className="primary"
              disabled={busy || symbol.trim().length < 3 || statement.trim().length < 10}
              onClick={() => void submit()}
            >
              {busy ? "memecah klaim…" : "simpan & pecah klaim"}
            </button>
          </div>
        </div>

        <div className="card">
          <h3 style={{ marginTop: 0 }}>Atau ambil dari angka</h3>
          <p className="sub">
            Agen membaca laporan kuartalan terbaru sektor perbankan dan menulis tesis yang <em>sudah</em> benar
            menurut data — titik awal untuk Anda edit, bukan saran investasi.
          </p>
          <button onClick={() => void suggest()} disabled={draftBusy}>
            {draftBusy ? "membaca laporan…" : "usulkan 3 tesis bank"}
          </button>
          {draftNote && <div className="dim" style={{ marginTop: 8 }}>{draftNote}</div>}
          {drafts.length > 0 && (
            <div className="col" style={{ marginTop: 12 }}>
              {drafts.map((draft) => (
                <div key={draft.symbol} className="card tight" style={{ marginBottom: 0 }}>
                  <div className="row">
                    <strong className="mono">{draft.symbol}</strong>
                    <span className="dim">{draft.company_name}</span>
                  </div>
                  <div style={{ margin: "6px 0" }}>{draft.statement}</div>
                  <button
                    onClick={() => {
                      setSymbol(draft.symbol);
                      setStatement(draft.statement);
                      setHorizon(draft.horizon);
                    }}
                  >
                    pakai ini
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}