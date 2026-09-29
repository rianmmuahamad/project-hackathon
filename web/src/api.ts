/**
 * Typed fetch wrapper. Every failure becomes an Error with the server's own
 * message, so the dashboard never shows a generic "something went wrong" over a
 * refusal the server explained precisely.
 */
import type {
  CheckDetail,
  Commodity,
  Decomposition,
  DraftResponse,
  Job,
  Notification,
  QueueRow,
  Stats,
  ThesisDetail,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text.slice(0, 400) };
    }
  }
  if (!response.ok) {
    const detail = errorDetail(payload, response.status);
    throw new Error(detail);
  }
  // Single boundary cast: the response schema is declared in `types.ts`, and the
  // server is the only producer. Every field is optional-checked at the render
  // site, so a shape drift shows up as a missing value rather than a crash.
  const typed = payload as T;
  return typed;
}

/** Pull `detail` out of an error payload without asserting its shape. */
function errorDetail(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string") return detail;
    if (detail !== undefined && detail !== null) return JSON.stringify(detail);
  }
  return `HTTP ${status}`;
}

export const api = {
  stats: () => request<Stats>("/api/stats"),
  queue: () => request<{ theses: QueueRow[] }>("/api/queue"),
  thesis: (id: string) => request<ThesisDetail>(`/api/thesis/${encodeURIComponent(id)}`),
  check: (id: string) => request<CheckDetail>(`/api/check/${encodeURIComponent(id)}`),
  notifications: (unreadOnly = false) =>
    request<{ notifications: Notification[] }>(`/api/notifications?unread_only=${unreadOnly}`),
  job: () => request<{ job: Job | null }>("/api/job"),
  draft: (subsector: string, count: number) =>
    request<DraftResponse>(
      `/api/draft?subsector=${encodeURIComponent(subsector)}&count=${count}`,
    ),

  commodities: () => request<{ commodities: Commodity[]; credits: number }>("/api/commodities"),
  createThesis: (body: { statement: string; symbol: string; horizon?: string; subject_type?: "equity" | "commodity" }) =>
    request<{ thesis: ThesisDetail; decomposition: Decomposition; engine_note: string | null; credits: number }>(
      "/api/thesis",
      { method: "POST", body: JSON.stringify(body) },
    ),
  updateClaims: (id: string, claims: Array<Record<string, unknown>>) =>
    request<ThesisDetail>(`/api/thesis/${encodeURIComponent(id)}/claims`, {
      method: "PUT",
      body: JSON.stringify({ claims }),
    }),
  checkThesis: (id: string, body: { engine?: string; budget?: number } = {}) =>
    request<{ started: boolean; job: Job | null }>(`/api/thesis/${encodeURIComponent(id)}/check`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  checkAll: (body: { all?: boolean; limit?: number; engine?: string } = {}) =>
    request<{ started: boolean; job: Job | null }>("/api/check-all", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  watch: (symbol: string, action: "add" | "remove") =>
    request<Record<string, unknown>>("/api/watch", {
      method: "POST",
      body: JSON.stringify({ symbol, action }),
    }),
  markRead: (id?: string) =>
    request<{ ok: boolean }>("/api/notifications/read", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),
};