import { useEffect, useState } from "react";

import { api } from "../api";
import type { Commodity, Decomposition, Draft } from "../types";

/**
 * Writing a thesis down.
 *
 * This screen is where the agent is most visible: a paragraph goes in, and
 * checkable claims come out — with the unverifiable half named rather than
 * dropped. The user confirms or edits before anything is trusted, because a
 * purpose-built interface for this one task is the product, not the model call.
 */
export function ComposePage({ onCreated }: { onCreated: (id: string) => void }) {
  const [subjectType, setSubjectType] = useState<"equity" | "commodity">("equity");
  const [symbol, setSymbol] = useState("");
  const [commoditiesList, setCommoditiesList] = useState<Commodity[]>([]);
  const [statement, setStatement] = useState("");
  const [horizon, setHorizon] = useState("2 quarters");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; split: Decomposition; credits: number } | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [skipped, setSkipped] = useState<Array<{ symbol: string; reason: string }>>([]);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftNote, setDraftNote] = useState<string | null>(null);

  useEffect(() => {
    api.commodities()
      .then((res) => setCommoditiesList(res.commodities || []))
      .catch(() => setCommoditiesList([]));
  }, []);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const payload = await api.createThesis({ symbol, statement, horizon, subject_type: subjectType });
      setResult({ id: payload.thesis.id, split: payload.decomposition, credits: payload.credits });
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
      setSkipped(payload.skipped ?? []);
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
    const unresolved = result.split.unresolved ?? [];
    return (
      <>
        <section className="qhead">
          <div className="qhead-top">
            <h1 className="headline">Saved thesis</h1>
            <span className="qhead-count micro muted">
              split into {result.split.claims.length} checkable claims
              {unresolved.length ? `, ${unresolved.length} not checkable` : ""}
            </span>
          </div>
          <div className="qstats">
            <span className="qstat">
              split by <b>{result.split.mode === "model" ? "model" : "offline heuristic"}</b>
            </span>
            <span className="qstat">
              <b>{result.credits}</b> baseline credits
            </span>
          </div>
        </section>

        {unresolved.length > 0 && (
          <div className="card" style={{ marginTop: "var(--s-lg)" }}>
            <span className="eyebrow">not checkable</span>
            <ul className="bullets body-sm muted" style={{ marginTop: 10 }}>
              {unresolved.map((item, index) => (
                <li key={index}>
                  {item.text} — <span className="dim">{item.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="pillrow" style={{ marginTop: "var(--s-xl)" }}>
          <button className="btn btn-primary" onClick={() => onCreated(result.id)}>
            Open thesis file
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => {
              setResult(null);
              setStatement("");
              setSymbol("");
            }}
          >
            Write another
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <section className="qhead">
        <div className="qhead-top">
          <h1 className="headline">New thesis</h1>
          <span className="qhead-count micro muted">the agent splits it into checkable claims</span>
        </div>
        {error && <div className="banner banner-bad">{error}</div>}
      </section>

      <section className="grid-2" style={{ marginTop: "var(--s-xl)" }}>
        <div>
          <div className="secttl">
            <span className="eyebrow">input</span>
            <h2 className="d-md">Thesis</h2>
          </div>
          <div className="stack" style={{ gap: "var(--s-md)" }}>
            <div className="pillrow">
              <button
                type="button"
                className={`btn btn-secondary ${subjectType === "equity" ? "btn-active" : ""}`}
                style={subjectType === "equity" ? { background: "var(--surface-sunken)", color: "var(--fg-loud)", borderColor: "var(--border-strong)" } : {}}
                onClick={() => { setSubjectType("equity"); setSymbol(""); }}
              >
                Equity (IDX)
              </button>
              <button
                type="button"
                className={`btn btn-secondary ${subjectType === "commodity" ? "btn-active" : ""}`}
                style={subjectType === "commodity" ? { background: "var(--surface-sunken)", color: "var(--fg-loud)", borderColor: "var(--border-strong)" } : {}}
                onClick={() => { setSubjectType("commodity"); setSymbol(""); }}
              >
                Commodity (Mining)
              </button>
            </div>
            <label className="field">
              <span>{subjectType === "commodity" ? "Commodity" : "Ticker (IDX)"}</span>
              {subjectType === "commodity" ? (
                <select
                  className="input"
                  value={symbol}
                  onChange={(event) => setSymbol(event.target.value)}
                >
                  <option value="">Select a commodity...</option>
                  {commoditiesList.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name} — {c.stale_days > 30 ? `${c.stale_days} days behind` : "current"}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="input"
                  value={symbol}
                  onChange={(event) => setSymbol(event.target.value.toUpperCase())}
                  placeholder="BBRI"
                />
              )}
            </label>
            <label className="field">
              <span>Thesis</span>
              <textarea
                className="input"
                value={statement}
                onChange={(event) => setStatement(event.target.value)}
                placeholder={
                  subjectType === "commodity"
                    ? "Harga nikel naik terus dan produksi nasional tumbuh dua digit."
                    : "Buy BBRI because loans grow at least 10% YoY and net interest income keeps rising, so earnings should keep climbing for two more quarters."
                }
              />
            </label>
            <label className="field">
              <span>Horizon</span>
              <input
                className="input"
                value={horizon}
                onChange={(event) => setHorizon(event.target.value)}
              />
            </label>
            <div>
              <button
                className="btn btn-primary"
                disabled={
                  busy ||
                  (subjectType === "equity" ? symbol.trim().length < 3 : !symbol.trim()) ||
                  statement.trim().length < 10
                }
                onClick={() => void submit()}
              >
                {busy ? "Splitting claims..." : "Save & split claims"}
              </button>
            </div>
          </div>
        </div>

        <div>
          <div className="secttl">
            <span className="eyebrow">suggestion</span>
            <h2 className="d-md">Or start from the numbers</h2>
            <p className="body-sm muted">
              The agent reads the latest quarterly reports for the banking sector and writes theses that
              already hold against the data — a starting point for you to edit, not investment advice.
            </p>
          </div>
          <div className="pillrow">
            <button className="btn btn-secondary" onClick={() => void suggest()} disabled={draftBusy}>
              {draftBusy ? "Reading reports..." : "Suggest 3 bank theses"}
            </button>
            {draftNote && <span className="micro muted">{draftNote}</span>}
          </div>

          {drafts.length > 0 && (
            <div className="stack" style={{ gap: "var(--s-sm)", marginTop: "var(--s-lg)" }}>
              {drafts.map((draft) => (
                <div className="card card-tight" key={draft.symbol}>
                  <div className="pillrow" style={{ gap: 10 }}>
                    <strong className="mono">{draft.symbol}</strong>
                    <span className="micro muted">{draft.company_name ?? ""}</span>
                  </div>
                  <p className="body-sm" style={{ margin: "8px 0 12px" }}>
                    {draft.statement}
                  </p>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: "8px 14px", minHeight: 34, fontSize: 13 }}
                    onClick={() => {
                      setSymbol(draft.symbol);
                      setStatement(draft.statement);
                      setHorizon(draft.horizon);
                    }}
                  >
                    Use this
                  </button>
                </div>
              ))}
            </div>
          )}

          {skipped.length > 0 && (
            <div className="banner banner-warn" style={{ marginTop: "var(--s-md)" }}>
              <strong>Could not draft:</strong>
              <ul className="bullets caption" style={{ marginTop: 6 }}>
                {skipped.map((item) => (
                  <li key={item.symbol}>
                    <span className="mono">{item.symbol}</span> — {item.reason}
                  </li>
                ))}
              </ul>
              <div className="dim micro" style={{ marginTop: 8 }}>
                The same guardrails used when checking a thesis also apply when writing one. Building a
                thesis on a broken data series washes that error into your sentence.
              </div>
            </div>
          )}
        </div>
      </section>
    </>
  );
}