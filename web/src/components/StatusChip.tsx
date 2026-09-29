import type { ClaimState, ThesisStatus } from "../types";
import { STATE_LABEL, STATUS_LABEL } from "../format";

/**
 * The status chip.
 *
 * The dot is a nested `<i>`, not a class on the chip itself: `.dot-*` sets a
 * background colour, so putting it on the chip would paint the whole chip and
 * override the surface the design gives it.
 */
function StatusPill({ tone, text }: { tone: ThesisStatus; text: string }) {
  return (
    <span className="chip">
      <i className={`dot dot-${tone}`} />
      {text}
    </span>
  );
}

export function StatusChip({ status }: { status: ThesisStatus | null | undefined }) {
  if (status === null || status === undefined) {
    // A check row exists from the moment it starts, before it has a verdict.
    // Showing UNKNOWN there would read as a conclusion; it is not one yet.
    return <StatusPill tone="unknown" text="RUNNING" />;
  }
  return <StatusPill tone={status} text={STATUS_LABEL[status]} />;
}

export function StateChip({ state }: { state: ClaimState | null | undefined }) {
  const value: ClaimState = state ?? "unknown";
  // The word follows the thesis vocabulary; the dot carries the claim's own
  // tone, which is why "supported" renders as INTACT with a green dot.
  const tone: ThesisStatus = value === "supported" ? "intact" : value === "weakening" ? "weakened"
    : value === "broken" ? "broken" : "unknown";
  return <StatusPill tone={tone} text={STATE_LABEL[value]} />;
}

/** Which layer produced the verdict — the product's central claim, made visible. */
export function DecisionBadge({ path }: { path: string | null | undefined }) {
  if (!path) return null;
  const titles: Record<string, string> = {
    jev: "decided by Jev from measured data; no agent turn needed",
    "jev+agent": "Jev decided the claims; the agent added context",
    agent_unverified: "the prose cited a figure the evidence does not contain",
    agent: "decided by the model alone; confidence is capped",
    measurement: "no interpretation layer was available",
  };
  const alert = path === "agent_unverified";
  return (
    <span className={`badge${alert ? " badge-alert" : ""}`} title={titles[path] ?? path}>
      {path.toUpperCase().replace("AGENT_UNVERIFIED", "UNVERIFIED")}
    </span>
  );
}