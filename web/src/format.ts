/** Presentation helpers. Formatting rules live here so no two screens disagree. */
import type { ClaimState, ThesisStatus } from "./types";

export const STATUS_LABEL: Record<ThesisStatus, string> = {
  intact: "INTACT",
  weakened: "WEAKENED",
  broken: "BROKEN",
  needs_review: "NEEDS REVIEW",
  unknown: "UNKNOWN",
};

export const STATUS_ORDER: ThesisStatus[] = ["broken", "needs_review", "weakened", "intact", "unknown"];

export const STATE_LABEL: Record<ClaimState, string> = {
  supported: "SUPPORTED",
  weakening: "WEAKENING",
  broken: "BROKEN",
  unknown: "UNKNOWN",
};

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

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}Rp${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}Rp${(abs / 1e9).toFixed(1)}M`;
  if (abs >= 1e6) return `${sign}Rp${(abs / 1e6).toFixed(0)}jt`;
  return `${sign}Rp${abs.toFixed(0)}`;
}

export function titleFor(symbol: string, name: string | null | undefined): string {
  return name ? `${symbol} · ${name}` : symbol;
}