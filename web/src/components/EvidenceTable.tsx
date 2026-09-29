import { useState } from "react";

import type { EvidenceRow } from "../types";

/**
 * Every number the verdict rests on, with the endpoint it came from.
 *
 * This is the audit surface: a judge takes any row and reproduces the call by
 * hand. So the component is built the way an audit view is — narrow by source,
 * search, expand for the full query, copy the call — rather than as a table you
 * have to read top to bottom.
 */
type Source = "api" | "tool" | "jev" | "guardrail";

const SOURCE_LABEL: Record<Source, string> = { api: "API", tool: "TOOL", jev: "JEV", guardrail: "GUARD" };

const SOURCE_ORDER: Source[] = ["api", "tool", "jev", "guardrail"];

/** Where a row came from. Endpoints are written in a fixed vocabulary by the loop. */
function sourceOf(row: EvidenceRow): Source {
  const endpoint = row.endpoint ?? "";
  const metric = row.metric ?? "";
  if (endpoint.startsWith("/v2/")) return "api";
  if (endpoint === "tool:jev") return metric.startsWith("guardrail.") ? "guardrail" : "jev";
  return "tool";
}

function parseParams(params: string | null): Record<string, unknown> | null {
  if (!params || params === "{}") return null;
  try {
    const parsed: unknown = JSON.parse(params);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** Only flat scalars can become a query string; anything nested takes the fallback form. */
function queryString(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      search.set(key, String(value));
    }
  }
  return search.toString();
}

/**
 * The command that reproduces this row.
 *
 * The key is a shell variable, never a value: a copied command must stay safe to
 * paste into a chat or a video description.
 */
function reproduction(row: EvidenceRow, sectorsBase: string): string {
  const params = parseParams(row.params);
  if (row.endpoint?.startsWith("/v2/") && params) {
    const qs = queryString(params);
    return `curl -s -H "Authorization: $SECTORS_API_KEY" "${sectorsBase}${row.endpoint}${qs ? `?${qs}` : ""}"`;
  }
  return `${row.endpoint ?? "?"} ${row.params ?? "{}"}`;
}

export function EvidenceTable({ rows, sectorsBase }: { rows: EvidenceRow[]; sectorsBase?: string }) {
  const [source, setSource] = useState<Source | "all">("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  if (!rows.length) return <p className="body-sm muted">No evidence rows were stored.</p>;

  const counts: Record<Source, number> = { api: 0, tool: 0, jev: 0, guardrail: 0 };
  for (const row of rows) counts[sourceOf(row)] += 1;

  const needle = query.trim().toLowerCase();
  const visible = rows.filter((row) => {
    if (source !== "all" && sourceOf(row) !== source) return false;
    if (!needle) return true;
    return [row.metric, row.value, row.endpoint, row.note]
      .some((field) => (field ?? "").toLowerCase().includes(needle));
  });

  async function copy(row: EvidenceRow) {
    if (!sectorsBase) return;
    try {
      await navigator.clipboard.writeText(reproduction(row, sectorsBase));
      setCopied(row.id);
      window.setTimeout(() => setCopied((current) => (current === row.id ? null : current)), 2000);
    } catch {
      // Clipboard access can be refused; leaving the command on screen is enough.
    }
  }

  return (
    <>
      <div className="toolbar">
        <button className={`fchip${source === "all" ? " on" : ""}`} onClick={() => setSource("all")}>
          All<b>{rows.length}</b>
        </button>
        {SOURCE_ORDER.filter((name) => counts[name] > 0).map((name) => (
          <button
            key={name}
            className={`fchip${source === name ? " on" : ""}`}
            onClick={() => setSource(name)}
            title={`only rows from ${SOURCE_LABEL[name]}`}
          >
            {SOURCE_LABEL[name]}
            <b>{counts[name]}</b>
          </button>
        ))}
        <input
          type="search"
          className="input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search metric, value, or endpoint"
          aria-label="Search evidence rows"
          style={{ width: "auto", minWidth: 180, maxWidth: 320, flex: 1, padding: "8px 12px", fontSize: 13 }}
        />
      </div>

      {visible.length === 0 ? (
        <p className="empty">No matching rows.</p>
      ) : (
        visible.map((row, index) => {
          const kind = sourceOf(row);
          const params = parseParams(row.params);
          const isOpen = open === row.id;
          const long = (row.metric ?? "").length > 40;
          return (
            <div key={row.id}>
              <div
                className={`erow${isOpen ? " open" : ""}`}
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : row.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setOpen(isOpen ? null : row.id);
                  }
                }}
              >
                {/* A synthetic guardrail row stores ordinal -1, so the display
                    index is positional and never the stored ordinal. */}
                <span className="idx num">{index + 1}</span>
                <span className={`srcbadge srcbadge-${kind}`}>{SOURCE_LABEL[kind]}</span>
                <span className={`metric${long ? " long" : ""}`}>{row.metric ?? "—"}</span>
                <span className="evalue">{row.value ?? "—"}</span>
              </div>

              {isOpen && (
                <div className="edetail">
                  <div className="mono dim">
                    {row.as_of ?? "no date"}
                    {row.symbol ? ` · ${row.symbol}` : ""} · ordinal {row.ordinal}
                  </div>
                  {row.note && (
                    <p className="body-sm" style={{ marginTop: 6 }}>
                      {row.note}
                    </p>
                  )}

                  <div className="caption muted" style={{ marginTop: 12 }}>
                    Parameters
                  </div>
                  <pre className="code">{params ? JSON.stringify(params, null, 2) : "no parameters"}</pre>

                  <div className="caption muted" style={{ marginTop: 12 }}>
                    How to replay this call
                  </div>
                  <pre className="code">{reproduction(row, sectorsBase ?? "")}</pre>
                  <button
                    className="btn btn-secondary"
                    style={{ marginTop: 10, padding: "8px 14px", minHeight: 34, fontSize: 13 }}
                    onClick={(event) => {
                      event.stopPropagation();
                      void copy(row);
                    }}
                    disabled={!sectorsBase}
                  >
                    {copied === row.id ? "Copied" : "Copy"}
                  </button>
                </div>
              )}
            </div>
          );
        })
      )}
    </>
  );
}