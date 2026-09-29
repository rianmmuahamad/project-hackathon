import { useEffect, useState } from "react";

import { api } from "../api";
import { ClaimList, ChangeStrip } from "../components/ChangeStrip";
import { EvidenceTable } from "../components/EvidenceTable";
import { DecisionBadge, StateChip, StatusChip } from "../components/StatusChip";
import { TranscriptView } from "../components/TranscriptView";
import { confidence, relative, shortDate } from "../format";
import type { CheckDetail, Job, ThesisDetail } from "../types";

/**
 * The thesis file: statement, timeline, evidence, transcript, replay.
 *
 * The sections are the product's argument. The change strip proves it has
 * memory. The claim table proves the reasoning was split into checkable parts.
 * The evidence table proves every number has a source. The transcript proves a
 * model chose the tools — including when it changed its own mind.
 */
export function ThesisWorkspace({
  id,
  refreshToken,
  onChanged,
  job,
}: {
  id: string;
  refreshToken: number;
  onChanged: () => void;
  job: Job | null;
}) {
  const [thesis, setThesis] = useState<ThesisDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selectedCheck, setSelectedCheck] = useState<string | null>(null);
  const [detail, setDetail] = useState<CheckDetail | null>(null);

  useEffect(() => {
    api
      .thesis(id)
      .then((payload) => {
        setThesis(payload);
        setError(null);
        const newest = payload.latest?.id ?? payload.checks[0]?.id ?? null;
        setSelectedCheck((current) => current ?? newest);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [id, refreshToken]);

  useEffect(() => {
    if (!selectedCheck) return;
    api
      .check(selectedCheck)
      .then(setDetail)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectedCheck, refreshToken]);

  async function runCheck() {
    setBusy(true);
    try {
      await api.checkThesis(id, {});
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleWatch() {
    if (!thesis) return;
    try {
      await api.watch(thesis.symbol, thesis.watch ? "remove" : "add");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (error && !thesis) return <div className="banner banner-bad">{error}</div>;
  if (!thesis) return <p className="body-sm muted" style={{ paddingTop: "var(--s-section)" }}>loading...</p>;

  const running = job?.state === "running";
  const unresolved = readUnresolved(thesis.translation);
  const changes = detail?.changes ?? thesis.recent_changes;

  return (
    <>
      <section className="qhead">
        <div className="qhead-top">
          <h1 className="headline">{thesis.symbol}</h1>
          <span className="qhead-count micro muted">
            {thesis.company_name ?? thesis.sub_sector ?? thesis.sector ?? ""}
          </span>
          <span className="spacer" />
          <div className="pillrow">
            <button className="btn btn-secondary" onClick={() => void toggleWatch()}>
              {thesis.watch ? "Unwatch" : "Watch"}
            </button>
            <button className="btn btn-primary" onClick={() => void runCheck()} disabled={busy || running}>
              {running ? "Running..." : "Check now"}
            </button>
          </div>
        </div>
        {error && <div className="banner banner-bad">{error}</div>}
        <p className="body-lg" style={{ fontSize: 20 }}>
          {thesis.statement}
        </p>
        <div className="qstats">
          <StatusChip status={thesis.status} />
          <span className="qstat">
            <b>{confidence(thesis.confidence)}</b> confidence
          </span>
          <span className="qstat">
            <b>{thesis.horizon ?? "—"}</b> horizon
          </span>
          <span className="qstat">
            <b>{thesis.claims.length}</b> claims
          </span>
          <span className="qstat">
            <b>{thesis.checks.length}</b> checks
          </span>
          <span className="qstat">
            <b>{thesis.source === "agent" ? "model" : "heuristic"}</b> splitter
          </span>
          {thesis.watermark && (
            <span className="qstat">
              watermark <b>{shortDate(thesis.watermark)}</b>
            </span>
          )}
        </div>
      </section>

      {detail && (
        <section className="section" style={{ marginTop: "var(--s-xl)" }}>
          <div className="card card-featured">
            <div className="pillrow">
              <StatusChip status={detail.verdict} />
              <DecisionBadge path={detail.decision_path} />
              <strong>confidence {confidence(detail.confidence)}</strong>
              {detail.confidence_source && (
                <span className="micro dim">from {detail.confidence_source}</span>
              )}
              <span className="spacer" />
              <span className="mono dim">
                {detail.engine ?? "?"} · {detail.tool_calls} tool calls · {detail.credits} credits
              </span>
            </div>
            <p className="body-lg" style={{ marginTop: "var(--s-md)", fontSize: 20, lineHeight: 1.6 }}>
              {detail.summary ?? "still running — the verdict is not in yet"}
            </p>
            <div className="mono dim" style={{ marginTop: 10 }}>
              {detail.checked_at}
              {detail.since && ` · watermark since ${shortDate(detail.since)}`}
              {!detail.finished && " · in progress"}
            </div>
          </div>
        </section>
      )}

      <section className="section" style={{ marginTop: "var(--s-xl)" }}>
        <div className="secttl">
          <span className="eyebrow">since last check</span>
          <h2 className="d-md">Changes</h2>
        </div>
        <div className="card">
          <ChangeStrip changes={changes} />
        </div>
      </section>

      <section className="section">
        <div className="secttl">
          <span className="eyebrow">split result</span>
          <h2 className="d-md">Checkable claims</h2>
        </div>
        <div className="card card-tight">
          <ClaimList claims={thesis.claims} />
          {unresolved.length > 0 && (
            <div className="banner banner-warn" style={{ marginTop: "var(--s-md)" }}>
              <strong>Not checkable with this data:</strong>
              <ul className="bullets caption" style={{ marginTop: 6 }}>
                {unresolved.map((item, index) => (
                  <li key={index}>
                    {item.text} — <span className="dim">{item.reason}</span>
                  </li>
                ))}
              </ul>
              <div className="dim micro" style={{ marginTop: 8 }}>
                Shown, not discarded. A thesis that is half unverifiable is itself a finding.
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="section">
        <div className="secttl">
          <span className="eyebrow">history</span>
          <h2 className="d-md">Checks</h2>
        </div>
        {thesis.checks.length > 0 && (
          <div
            className="pillrow"
            style={{ marginBottom: "var(--s-md)", overflowX: "auto", paddingBottom: 4, flexWrap: "nowrap" }}
          >
            {thesis.checks.map((check) => (
              <button
                key={check.id}
                className={`btn ${check.id === selectedCheck ? "btn-primary" : "btn-secondary"}`}
                onClick={() => setSelectedCheck(check.id)}
                title={check.summary ?? ""}
              >
                <StatusChip status={check.verdict} />
                <span className="mono dim" style={{ fontSize: 12 }}>
                  {relative(check.checked_at)}
                </span>
              </button>
            ))}
          </div>
        )}

        {detail ? (
          <>
            <div className="secttl" style={{ marginTop: "var(--s-xl)" }}>
              <span className="eyebrow">per claim</span>
              <h3 className="d-md">Per-claim results</h3>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th style={{ width: 130 }}>Status</th>
                    <th>Claim</th>
                    <th style={{ width: 130, minWidth: 140 }}>Observed</th>
                    <th style={{ width: 110 }} className="num">
                      YoY
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {detail.claim_results.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <StateChip state={row.state} />
                      </td>
                      <td>
                        {row.text}
                        <div className="micro dim" style={{ marginTop: 6 }}>
                          {row.rationale}
                        </div>
                      </td>
                      <td className="mono dim">{shortDate(row.observed_date)}</td>
                      <td className="mono num">{row.delta ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="secttl" style={{ marginTop: "var(--s-xl)" }}>
              <span className="eyebrow">trace</span>
              <h3 className="d-md">Evidence — every number with its source</h3>
            </div>
            <div className="card card-tight">
              <EvidenceTable rows={detail.evidence} sectorsBase={detail.sectors_base} />
            </div>

            <div className="secttl" style={{ marginTop: "var(--s-xl)" }}>
              <span className="eyebrow">agent loop</span>
              <h3 className="d-md">Agent transcript</h3>
              <p className="body-sm muted">
                The tools below were picked by the agent, not a script. You can see which tools it reached
                for, what they cost, and where it changed its own mind.
              </p>
            </div>
            <TranscriptView segments={detail.transcript_segments ?? []} markdown={detail.transcript} />
          </>
        ) : (
          <div className="card">
            <p className="body-sm muted">
              Not checked yet. Click <strong>Check now</strong> — the agent loop appears in the agent log.
            </p>
          </div>
        )}
      </section>
    </>
  );
}

/** Read the decomposition's unresolved list out of the stored JSON, defensively. */
function readUnresolved(translation: string | null): Array<{ text: string; reason: string }> {
  if (!translation) return [];
  try {
    const parsed: unknown = JSON.parse(translation);
    if (!parsed || typeof parsed !== "object" || !("unresolved" in parsed)) return [];
    const list = parsed.unresolved;
    if (!Array.isArray(list)) return [];
    return list
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
      .map((item) => ({
        text: typeof item.text === "string" ? item.text : JSON.stringify(item),
        reason: typeof item.reason === "string" ? item.reason : "",
      }));
  } catch {
    return [];
  }
}