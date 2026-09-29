import { useEffect, useState } from "react";

import { api } from "../api";
import { LiveJob } from "../components/LiveJob";
import { ClaimList, ChangeStrip } from "../components/ChangeStrip";
import { EvidenceTable } from "../components/EvidenceTable";
import { StatusChip } from "../components/StatusChip";
import { TranscriptView } from "../components/TranscriptView";
import { confidence, relative, shortDate, titleFor } from "../format";
import type { CheckDetail, Job, ThesisDetail } from "../types";

/**
 * The thesis file: statement, timeline, evidence, transcript, replay.
 *
 * The four panes are the product's argument. The change strip proves it has
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

  if (error && !thesis) return <div className="banner bad">{error}</div>;
  if (!thesis) return <p className="dim">loading…</p>;

  const running = job?.state === "running";
  const decompositionUnresolved = readUnresolved(thesis.translation);

  return (
    <>
      <h1>{titleFor(thesis.symbol, thesis.company_name)}</h1>
      <p className="lead">{thesis.statement}</p>

      {error && <div className="banner bad">{error}</div>}

      <div className="row wrap" style={{ marginBottom: 16 }}>
        <StatusChip status={thesis.status} />
        <span className="sub">
          confidence {confidence(thesis.confidence)} · horizon {thesis.horizon ?? "—"} ·{" "}
          {thesis.source === "agent" ? "dipecah model" : "dipecah heuristik"}
        </span>
        <span className="grow" />
        <button className="primary" onClick={() => void runCheck()} disabled={busy || running}>
          {running ? "berjalan…" : "periksa sekarang"}
        </button>
        <button onClick={() => void toggleWatch()}>{thesis.watch ? "lepas pantau" : "pantau"}</button>
      </div>

      <h2>Perubahan sejak pemeriksaan terakhir</h2>
      <div className="card">
        <ChangeStrip changes={detail?.changes ?? thesis.recent_changes} />
      </div>

      <h2>Klaim yang bisa diperiksa</h2>
      <div className="card tight">
        <ClaimList claims={thesis.claims} />
        {decompositionUnresolved.length > 0 && (
          <div className="banner warn" style={{ marginTop: 12, marginBottom: 0 }}>
            <strong>Tidak bisa diperiksa dengan data ini:</strong>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {decompositionUnresolved.map((item, index) => (
                <li key={index}>
                  {item.text} — <span className="dim">{item.reason}</span>
                </li>
              ))}
            </ul>
            <div className="dim" style={{ marginTop: 6 }}>
              Ini ditampilkan, bukan dibuang. Tesis yang separuh tidak bisa diverifikasi adalah temuan.
            </div>
          </div>
        )}
      </div>

      <h2>Pemeriksaan</h2>
      {thesis.checks.length > 0 && (
        <div className="row wrap" style={{ marginBottom: 10 }}>
          {thesis.checks.map((check) => (
            <button
              key={check.id}
              className={check.id === selectedCheck ? "primary" : ""}
              onClick={() => setSelectedCheck(check.id)}
              title={check.summary ?? ""}
            >
              <StatusChip status={check.verdict} /> <span className="mono dim">{relative(check.checked_at)}</span>
            </button>
          ))}
        </div>
      )}

      {detail ? (
        <>
          <div className="card">
            <div className="card-head">
              <StatusChip status={detail.verdict} />
              {detail.decision_path && <DecisionBadge path={detail.decision_path} />}
              <strong>confidence {confidence(detail.confidence)}</strong>
              {detail.confidence_source && (
                <span className="dim">from {detail.confidence_source}</span>
              )}
              <span className="spacer" />
              <span className="dim mono">
                {detail.engine ?? "?"} · {detail.tool_calls} tool call(s) · {detail.credits} credits
              </span>
            </div>
            <p style={{ margin: "4px 0 0" }}>{detail.summary ?? "still running — the verdict is not in yet"}</p>
            <div className="dim mono" style={{ marginTop: 6 }}>
              {detail.checked_at}
              {detail.since && ` · watermark since ${shortDate(detail.since)}`}
              {!detail.finished && " · in progress"}
            </div>
          </div>

          <h3>Hasil per klaim</h3>
          <table>
            <thead>
              <tr>
                <th style={{ width: 110 }}>Status</th>
                <th>Klaim</th>
                <th style={{ width: 150 }}>Terukur</th>
                <th style={{ width: 90 }}>YoY</th>
              </tr>
            </thead>
            <tbody>
              {detail.claim_results.map((row) => (
                <tr key={row.id}>
                  <td>
                    <span
                      className={`chip ${
                        row.state === "supported"
                          ? "intact"
                          : row.state === "weakening"
                            ? "weakened"
                            : row.state === "broken"
                              ? "broken"
                              : "unknown"
                      }`}
                    >
                      {row.state.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    {row.text}
                    <div className="dim">{row.rationale}</div>
                  </td>
                  <td className="mono dim">{shortDate(row.observed_date)}</td>
                  <td className="mono">{row.delta ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Bukti — setiap angka dengan sumbernya</h3>
          <div className="card tight">
            <EvidenceTable rows={detail.evidence} sectorsBase={detail.sectors_base} />
          </div>

          <h3>Transkrip agen</h3>
          <div className="card">
            <p className="sub" style={{ marginTop: 0 }}>
              Tool di bawah dipilih oleh agen, bukan skrip. Anda bisa melihat alat apa yang ia raih, berapa
              kreditnya, dan di mana ia mengubah kesimpulannya sendiri.
            </p>
            <TranscriptView
              segments={detail.transcript_segments ?? []}
              markdown={detail.transcript}
            />
          </div>
        </>
      ) : (
        <p className="dim">
          Belum pernah diperiksa. Klik <strong>periksa sekarang</strong> — loop agen akan terlihat di panel
          bawah.
        </p>
      )}

      <LiveJob job={job} onFinished={onChanged} />
    </>
  );
}

/** Which layer produced the verdict — the product's central claim, made visible. */
function DecisionBadge({ path }: { path: string }) {
  if (path === "jev") return <span className="chip intact" title="decided by Jev from measured data; no agent turn needed">JEV</span>;
  if (path === "jev+agent") return <span className="chip ghost" title="Jev decided the claims; the agent added context">JEV+AGENT</span>;
  if (path === "agent_unverified") return <span className="chip broken" title="the prose cited a figure the evidence does not contain">UNVERIFIED</span>;
  if (path === "agent") return <span className="chip ghost" title="decided by the model alone; confidence is capped">AGENT</span>;
  if (path === "measurement") return <span className="chip ghost" title="no interpretation layer was available">MEASURED</span>;
  return null;
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