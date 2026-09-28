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
    return <p className="dim">Nothing has changed since the last check. That is the answer.</p>;
  }
  return (
    <div className="strip">
      {changes.map((change) => (
        <div className="item" key={change.id}>
          <span className="tag">{change.kind ?? "data"}</span>
          <span>
            {change.text}
            {change.magnitude && <span className="muted"> · {change.magnitude}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

export function ClaimList({ claims }: { claims: Claim[] }) {
  if (!claims.length) return <p className="dim">No checkable claims were extracted.</p>;
  return (
    <table>
      <thead>
        <tr>
          <th style={{ width: 30 }}>#</th>
          <th>Claim</th>
          <th style={{ width: 150 }}>Metric</th>
          <th style={{ width: 90 }}>Direction</th>
          <th style={{ width: 110 }}>Baseline</th>
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
  );
}