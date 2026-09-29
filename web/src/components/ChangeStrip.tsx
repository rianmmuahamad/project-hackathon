import type { Claim, Change } from "../types";
import { shortDate } from "../format";

/**
 * "What is different since you last looked."
 *
 * The strip is the visible proof that the product has memory: it exists because
 * a previous check set a watermark, and it only lists things newer than it.
 */
export function ChangeStrip({ changes }: { changes: Change[] }) {
  if (!changes.length) {
    return <p className="body-sm muted">Nothing has changed since the last check. That is the answer.</p>;
  }
  return (
    <div className="chg">
      {changes.map((change) => (
        <div className="chg-row" key={change.id}>
          <span className="tag chg-tag">{change.kind ?? "data"}</span>
          <span className="chg-body">
            <span className="chg-text">{change.text}</span>
            {change.magnitude && <span className="chg-mag">{change.magnitude}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

export function ClaimList({ claims }: { claims: Claim[] }) {
  if (!claims.length) return <p className="body-sm muted">No checkable claims were extracted.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="tbl">
        <thead>
          <tr>
            <th style={{ width: 34 }} className="num">
              #
            </th>
            <th>Claim</th>
            <th style={{ width: 150, minWidth: 140 }}>Metric</th>
            <th style={{ width: 120 }}>Direction</th>
            <th style={{ width: 110, minWidth: 110 }}>Baseline</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((claim) => (
            <tr key={claim.id}>
              <td className="num muted">{claim.ordinal + 1}</td>
              <td>{claim.text}</td>
              <td className="mono">{claim.metric ?? <span className="dim">unresolved</span>}</td>
              <td className="mono">
                {claim.direction ?? "—"}
                {claim.threshold !== null && (
                  <span className="dim">
                    {" "}
                    {claim.comparator ?? ">="} {claim.threshold}
                  </span>
                )}
              </td>
              <td className="mono dim">
                {claim.baseline_value === null ? "—" : shortDate(claim.baseline_date)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}