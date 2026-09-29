/**
 * Presentation vocabulary, in one place so no two screens disagree.
 *
 * The labels match the design reference exactly: a claim's `supported` state
 * reads "INTACT" on screen, because that is the word the design uses for it.
 */
import type { ClaimState, ThesisStatus } from "./types";

export const STATUS_LABEL: Record<ThesisStatus, string> = {
  intact: "INTACT",
  weakened: "WEAKENED",
  broken: "BROKEN",
  needs_review: "REVIEW",
  unknown: "UNKNOWN",
};

export const STATUS_ORDER: ThesisStatus[] = ["broken", "needs_review", "weakened", "intact", "unknown"];

/** Claim states reuse the thesis vocabulary on purpose; the dot colour differs, not the word. */
export const STATE_LABEL: Record<ClaimState, string> = {
  supported: "INTACT",
  weakening: "WEAKENED",
  broken: "BROKEN",
  unknown: "UNKNOWN",
};

/** Severity of a notification, mapped onto the status tones. */
export function severityTone(severity: string): ThesisStatus {
  if (severity === "alert") return "broken";
  if (severity === "warning") return "weakened";
  if (severity === "ok") return "intact";
  return "unknown";
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = new Date(iso.replace(/(\d{2})(\d{2})$/, "$1:$2")).getTime();
  if (Number.isNaN(then)) return iso;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

export function confidence(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(2);
}