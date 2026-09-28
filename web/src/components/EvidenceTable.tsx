import type { EvidenceRow } from "../types";

/**
 * Every number the verdict rests on, with the endpoint it came from.
 *
 * This table is the audit surface: a judge (or the user) can take any row and
 * reproduce the call by hand. `params` is shown, never hidden, because a number
 * without its query is not evidence.
 */
export function EvidenceTable({ rows }: { rows: EvidenceRow[] }) {
  if (!rows.length) return <p className="dim">No evidence rows were stored.</p>;
  return (
    <table>
      <thead>
        <tr>
          <th style={{ width: 30 }}>#</th>
          <th style={{ width: 220 }}>Metric</th>
          <th style={{ width: 190 }}>Value</th>
          <th style={{ width: 100 }}>As of</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td className="num muted">{row.ordinal + 1}</td>
            <td className="mono">{row.metric ?? "—"}</td>
            <td className="mono">{row.value ?? "—"}</td>
            <td className="mono dim">{row.as_of ?? "—"}</td>
            <td className="mono dim">
              {row.endpoint ?? "—"}
              {row.params && row.params !== "{}" && (
                <details>
                  <summary>params</summary>
                  <code>{row.params}</code>
                </details>
              )}
              {row.note && <div className="dim">{row.note}</div>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}