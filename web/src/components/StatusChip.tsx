import type { ClaimState, ThesisStatus } from "../types";
import { STATE_LABEL, STATUS_LABEL } from "../format";

/** The product's vocabulary, in one place so every screen uses the same words. */
export function StatusChip({ status }: { status: ThesisStatus | null | undefined }) {
  const value: ThesisStatus = status ?? "unknown";
  return <span className={`chip ${value}`}>{STATUS_LABEL[value]}</span>;
}

export function StateChip({ state }: { state: ClaimState | null | undefined }) {
  const value: ClaimState = state ?? "unknown";
  const tone = value === "supported" ? "intact" : value === "weakening" ? "weakened" : value === "broken" ? "broken" : "unknown";
  return <span className={`chip ${tone}`}>{STATE_LABEL[value]}</span>;
}