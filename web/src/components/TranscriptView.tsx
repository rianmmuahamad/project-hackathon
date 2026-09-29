import { useState } from "react";

import type { TranscriptSegment } from "../types";

/**
 * The agent transcript, as segments rather than a wall of text.
 *
 * The file on disk is structured — a preamble then `## ` sections — and that
 * structure is what makes the run readable: what Jev decided, which tool the
 * agent reached for, what the guardrail found. Collapsed rows carry the shape;
 * expanding one carries the evidence.
 *
 * A raw toggle stays, because this is an audit artifact and the on-screen text
 * should still be checkable against the `.md` file.
 */
export function TranscriptView({ segments, markdown }: { segments: TranscriptSegment[]; markdown?: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const [raw, setRaw] = useState(false);

  if (!segments.length) {
    if (!markdown) return <p className="body-sm muted">No transcript was stored for this check.</p>;
    return (
      <>
        <div className="banner banner-warn" style={{ marginBottom: 10 }}>
          The transcript could not be split into sections; shown as-is.
        </div>
        <div className="transcript">{markdown}</div>
      </>
    );
  }

  return (
    <>
      <div className="toolbar">
        <span className="micro muted">{segments.length} sections</span>
        <span className="spacer" />
        <button
          className="btn btn-secondary"
          style={{ padding: "8px 14px", minHeight: 34, fontSize: 13 }}
          onClick={() => setRaw(!raw)}
        >
          {raw ? "View structured" : "View raw"}
        </button>
      </div>

      {raw ? (
        <div className="transcript">{markdown ?? "(no transcript stored)"}</div>
      ) : (
        segments.map((segment) => {
          const isOpen = open === segment.ordinal;
          return (
            <div key={segment.ordinal} className={`seg${isOpen ? " open" : ""}`}>
              <button
                className="seg-head"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : segment.ordinal)}
              >
                <span className={`kbadge kbadge-${segment.kind}`}>{segment.label}</span>
                <span className="mono dim">{segment.title}</span>
                <span className="spacer" />
                {segment.evidence_ordinals.length > 0 && (
                  <span className="micro muted">{segment.evidence_ordinals.length} evidence</span>
                )}
                <span className="muted seg-chev">{isOpen ? "▾" : "▸"}</span>
              </button>

              {!isOpen && segment.summary && <div className="seg-sum">{segment.summary}</div>}

              {isOpen && <div className="seg-body">{renderBody(segment.body)}</div>}
            </div>
          );
        })
      )}
    </>
  );
}

/**
 * Render a markdown body without a markdown library: fenced blocks become code,
 * everything else becomes paragraphs. The point is separating prose from payload
 * so a 4,000-character JSON blob stops looking like a paragraph.
 */
function renderBody(body: string) {
  const parts: Array<{ kind: "prose" | "code"; text: string }> = [];
  let pending: string[] = [];
  let fenced: string[] | null = null;

  const flushProse = () => {
    const text = pending.join("\n").trim();
    if (text) parts.push({ kind: "prose", text });
    pending = [];
  };

  for (const line of body.split("\n")) {
    if (line.trim().startsWith("```")) {
      if (fenced === null) {
        flushProse();
        fenced = [];
      } else {
        parts.push({ kind: "code", text: fenced.join("\n") });
        fenced = null;
      }
      continue;
    }
    if (fenced !== null) fenced.push(line);
    else pending.push(line);
  }
  if (fenced !== null) parts.push({ kind: "code", text: fenced.join("\n") });
  flushProse();

  return parts.map((part, index) =>
    part.kind === "code" ? (
      <pre className="code" key={index}>
        {prettyJson(part.text)}
      </pre>
    ) : (
      <p className="prose" key={index}>
        {part.text}
      </p>
    ),
  );
}

/** Re-indent a JSON payload so it is readable; leave anything else untouched. */
function prettyJson(text: string): string {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return text;
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return text;
  }
}