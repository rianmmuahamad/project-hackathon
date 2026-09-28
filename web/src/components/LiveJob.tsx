import { useEffect, useRef, useState } from "react";

import type { Job, JobEvent } from "../types";

/**
 * The live transcript of whatever the agent is doing right now.
 *
 * This is the part that makes the product legible as an agent rather than a
 * dashboard: you can watch it decide which tool to reach for, and see the
 * credits each call costs, while it works.
 */
export function LiveJob({ job, onFinished }: { job: Job | null; onFinished?: () => void }) {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [state, setState] = useState<string>("idle");
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const finishedRef = useRef(onFinished);
  finishedRef.current = onFinished;

  useEffect(() => {
    setEvents([]);
    setError(null);
    const source = new EventSource("/api/events");

    source.addEventListener("step", (raw) => {
      const message = raw as MessageEvent<string>;
      try {
        const parsed: unknown = JSON.parse(message.data);
        if (parsed && typeof parsed === "object" && "kind" in parsed) {
          setEvents((prev) => [...prev, parsed as JobEvent]);
        }
      } catch {
        /* a malformed frame is skipped, not rendered as garbage */
      }
    });

    source.addEventListener("finished", (raw) => {
      const message = raw as MessageEvent<string>;
      try {
        const parsed: unknown = JSON.parse(message.data);
        if (parsed && typeof parsed === "object" && "state" in parsed) {
          const record = parsed as Record<string, unknown>;
          setState(typeof record.state === "string" ? record.state : "done");
          setError(typeof record.error === "string" ? record.error : null);
        }
      } catch {
        setState("done");
      }
      source.close();
      finishedRef.current?.();
    });

    source.addEventListener("idle", () => setState("idle"));
    source.onerror = () => {
      /* EventSource retries on its own; nothing useful to show for a blip */
    };

    return () => source.close();
  }, [job?.started_at]);

  useEffect(() => {
    if (events.length > 0 && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [events.length]);

  const running = state === "running" || (job?.state === "running" && state !== "done");

  return (
    <div className="live">
      <div className="live-head">
        {running && <span className="pulse" />}
        <strong>{job ? job.kind : "no job"}</strong>
        <span className="dim">
          {job?.symbol ? `${job.symbol} · ` : ""}
          {running ? "working" : state === "idle" ? "idle" : state}
        </span>
        <span className="grow" />
        <span className="dim">{events.length} step(s)</span>
      </div>
      {error && <div className="banner bad" style={{ margin: "10px 14px" }}>{error}</div>}
      <ol ref={listRef}>
        {events.length === 0 && (
          <li className="dim">
            {running ? "waiting for the first step…" : "start a check to watch the agent work"}
          </li>
        )}
        {events.map((event, index) => (
          <li key={index} className={event.kind}>
            <span className="at">{event.at}</span>
            <span>{describe(event)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function describe(event: JobEvent): string {
  if (event.kind === "tool") {
    const args = event.args && typeof event.args === "object" ? JSON.stringify(event.args) : "";
    return `tool → ${String(event.tool)}(${args.slice(0, 110)})`;
  }
  if (event.kind === "tool_result") {
    return `      ${String(event.tool)} cost ${String(event.credits)} credit(s)`;
  }
  if (event.kind === "thinking") return `round ${String(event.round)} — deciding`;
  if (event.kind === "measured") {
    return `measured without a model: ${String(event.status)} — ${String(event.reason)}`;
  }
  if (event.kind === "thesis") return `checking ${String(event.symbol)}`;
  if (event.kind === "engine") return `engine: ${String(event.detail)}`;
  if (event.kind === "done") {
    return `verdict ${String(event.status)} (confidence ${String(event.confidence)})`;
  }
  return event.kind;
}