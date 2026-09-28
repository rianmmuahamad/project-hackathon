import type { ClaimState, ThesisStatus } from "../types";
import { STATE_LABEL, STATUS_LABEL } from "../format";

/** The product's vocabulary, in one place so every screen uses the same words. */
export function StatusChip({ status }: { status: ThesisStatus | null | undefined }) {
  if (status === null || status === undefined) {
    // A check row exists from the moment it starts, before it has a verdict.
    // Showing UNKNOWN there would read as a conclusion; it is not one yet.
    return <span className="chip ghost">RUNNING</span>;
  }
  return <span className={`chip ${status}`}>{STATUS_LABEL[status]}</span>;
}

export function StateChip({ state }: { state: ClaimState | null | undefined }) {
  const value: ClaimState = state ?? "unknown";
  const tone = value === "supported" ? "intact" : value === "weakening" ? "weakened" : value === "broken" ? "broken" : "unknown";
  return <span className={`chip ${tone}`}>{STATE_LABEL[value]}</span>;
}