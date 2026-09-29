import { useEffect, useState } from "react";

import { api } from "../api";
import type { Job, QueueRow, Stats } from "../types";
import { relative, shortDate, STATUS_ORDER, STATUS_LABEL } from "../format";

/**
 * The worklist. Worst first.
 *
 * A user does not start from "run a scan": they start from "which of the things
 * I own no longer make sense?" The queue answers that, and check-all is the
 * recurring routine — not a search box.
 */
export function QueuePage({
  refreshToken,
  onChanged,
  job,
  stats,
}: {
  refreshToken: number;
  onChanged: () => void;
  job: Job | null;
  stats: Stats | null;
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
  const watched = rows.filter((row) => row.watch).length;
  const summary = STATUS_ORDER.filter((status) => counts[status])
    .map((status) => `${counts[status]} ${STATUS_LABEL[status].toLowerCase()}`)
    .join(" · ");
  const store = stats?.store;
  const credits = stats?.credits;
  const engineName =
    Object.entries(stats?.engine ?? {}).find(([, info]) => info.available)?.[0] ?? "none";
  const jev = stats?.jev;
  const schedule = stats?.schedule;

  return (
    <>
      <section className="qhead">
        <div className="qhead-top">
          <h1 className="headline">Thesis queue</h1>
          <span className="qhead-count micro muted">
            {rows.length} theses · {summary || "no theses yet"}
          </span>
          <span className="spacer" />
          <div className="pillrow">
            <a href="#/new">
              <button className="btn btn-secondary" type="button">
                + New thesis
              </button>
            </a>
            <button className="btn btn-primary" onClick={() => void checkAll()} disabled={busy || running}>
              {running ? "Running..." : "Check all"}
            </button>
          </div>
        </div>
        {error && <div className="banner banner-bad">{error}</div>}
        <div className="qstats">
          <span className="qstat">
            <b>
              {watched}/{rows.length}
            </b>{" "}
            watched
          </span>
          <span className="qstat">
            <b>{store ? store.checks : "—"}</b> checks
          </span>
          <span className="qstat">
            <b>{credits ? credits.credits_spent : "—"}</b> credits
            {credits ? ` (${credits.network_calls} network · ${credits.cached_calls} cached)` : ""}
          </span>
          <span className="qstat">
            <b>{engineName}</b> engine
          </span>
          <span className="qstat">
            <b>{jev?.available ? (jev.model ?? "on") : "off"}</b> jev
          </span>
          <span className="qstat">
            <b>
              {schedule?.next
                ? `${shortDate(schedule.next)} ${schedule.next.slice(11, 16)}`
                : "off"}
            </b>{" "}
            next check
          </span>
          <span className="qstat">
            <b>{schedule?.email_configured ? "on" : "off"}</b> email
          </span>
        </div>
      </section>

      <section className="section" style={{ marginTop: "var(--s-xl)" }}>
        {rows.length === 0 ? (
          <div className="card">
            <p className="empty">
              No theses yet. Write one in <a href="#/new">New thesis</a> — for example{" "}
              <em>&ldquo;BBRI loans grow at least 10% YoY&rdquo;</em>.
            </p>
          </div>
        ) : (
          <div className="list">
            {rows.map((row) => {
              const change = row.changes.length ? row.changes[0] : null;
              return (
                <a className="rowcard" key={row.id} href={`#/thesis/${row.id}`}>
                  <div className="rowcard-top">
                    <span className="chip">
                      <i className={`dot dot-${row.status}`} />
                      {STATUS_LABEL[row.status]}
                    </span>
                    <span className="rowcard-sym">{row.symbol}</span>
                    {row.subject_type === "commodity" && (
                      <span className="tag" style={{ marginLeft: 8 }}>
                        COMMODITY
                      </span>
                    )}
                    <span className="spacer" />
                    <span className="rowcard-conf">
                      confidence <b>{row.confidence === null ? "—" : row.confidence.toFixed(2)}</b>
                    </span>
                  </div>
                  {row.company_name && <div className="rowcard-cname">{row.company_name}</div>}
                  <p className="rowcard-stmt">{row.statement}</p>
                  <div className="rowcard-delta">
                    <span className="arw">↳</span>
                    <span>
                      {change ? (
                        <>
                          {change.text}
                          {change.magnitude && <span className="muted"> · {change.magnitude}</span>}
                        </>
                      ) : (
                        <span className="muted">{row.last_check?.summary ?? "Never checked."}</span>
                      )}
                    </span>
                  </div>
                  <div className="rowcard-meta">
                    <span className="meta-group">
                      <span>{row.claims} claims</span>
                      <span>{row.last_check ? `${row.last_check.tool_calls} tool calls` : "—"}</span>
                      <span title={row.last_checked_at ?? ""}>{relative(row.last_checked_at)}</span>
                    </span>
                    <span className="spacer" />
                    <span className="meta-group">
                      {row.watermark && <span>watermark since {shortDate(row.watermark)}</span>}
                      {row.watch && (
                        <span className="tag">
                          <i className="dot dot-intact" />
                          watched
                        </span>
                      )}
                    </span>
                  </div>
                </a>
              );
            })}
          </div>
        )}
      </section>

      <section className="section">
        <div className="secttl">
          <span className="eyebrow">delivery</span>
          <h2 className="d-md">Scheduled digests</h2>
        </div>
        <div className="card card-tight">
          {schedule && schedule.digests.length > 0 ? (
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 150, minWidth: 140 }}>When</th>
                  <th>Delivery</th>
                  <th style={{ width: 110 }} className="num">
                    Checked
                  </th>
                  <th style={{ width: 110 }} className="num">
                    Changed
                  </th>
                </tr>
              </thead>
              <tbody>
                {schedule.digests.map((run) => (
                  <tr key={run.at}>
                    <td className="mono dim">
                      {shortDate(run.at)} {run.at.slice(11, 16)}
                    </td>
                    <td>
                      {run.emailed ? (
                        <>
                          sent
                          {run.to && run.to.length > 0 && (
                            <div className="micro dim" style={{ marginTop: 6 }}>
                              {run.to.join(", ")}
                            </div>
                          )}
                        </>
                      ) : run.error ? (
                        <span className="dim">{run.error}</span>
                      ) : (
                        <span className="dim">{run.reason ?? run.note ?? "not sent"}</span>
                      )}
                    </td>
                    <td className="mono num">{run.checked}</td>
                    <td className="mono num">{run.changed === 0 ? "—" : run.changed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="empty">No scheduled run yet this session.</p>
          )}
        </div>
      </section>

      <section className="section">
        <div className="secttl">
          <span className="eyebrow">how it works</span>
          <h2 className="d-md">How this product works</h2>
        </div>
        <div className="grid-2">
          <div className="card">
            <h3 className="headline">Numbers are computed in code, judgment by the agent</h3>
            <p className="body-sm muted" style={{ marginTop: 10 }}>
              Latest values, YoY changes, and threshold tests are computed in Python from stored data. No
              number in a verdict is typed by the model. The agent uses them to answer what cannot be
              computed: whether a move belongs to the company or the whole market, whether a price moved on
              corporate action, and whether the written thesis still makes sense.
            </p>
          </div>
          <div className="card">
            <h3 className="headline">Watermark</h3>
            <p className="body-sm muted" style={{ marginTop: 10 }}>
              Every check stores a date. The next check only reads what is new since that date — which is why
              the &ldquo;latest change&rdquo; row above has content, and why re-checking costs almost no
              credits.
            </p>
          </div>
        </div>
      </section>
    </>
  );
}