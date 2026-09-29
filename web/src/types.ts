/**
 * Wire types. These mirror the JSON the Python service returns; the dashboard
 * has no other source of truth about a thesis.
 */

export type ThesisStatus = "intact" | "weakened" | "broken" | "needs_review" | "unknown";
export type ClaimState = "supported" | "weakening" | "broken" | "unknown";

export interface Claim {
  id: string;
  thesis_id: string;
  ordinal: number;
  text: string;
  metric: string | null;
  direction: string | null;
  cadence: string;
  threshold: number | null;
  comparator: string | null;
  baseline_value: number | null;
  baseline_date: string | null;
}

export interface Change {
  id: string;
  thesis_id: string;
  check_id: string | null;
  ordinal: number;
  kind: string | null;
  text: string;
  magnitude: string | null;
  evidence_ord: number | null;
}

export interface CheckSummary {
  id: string;
  thesis_id: string;
  run_id: string | null;
  checked_at: string;
  since: string | null;
  /** null while the check is still running — not yet a verdict. */
  verdict: ThesisStatus | null;
  confidence: number | null;
  summary: string | null;
  engine: string | null;
  model: string | null;
  credits: number;
  tool_calls: number;
  transcript_path: string | null;
  /** Which layer decided: jev | jev+agent | agent | agent_unverified | measurement. */
  decision_path: string | null;
  /** Where the confidence number came from: jev | prose | rule. */
  confidence_source: string | null;
}

export interface ClaimResult {
  id: string;
  claim_id: string | null;
  ordinal: number;
  text: string;
  state: ClaimState;
  observed_value: number | null;
  observed_date: string | null;
  delta: string | null;
  rationale: string | null;
}

export interface EvidenceRow {
  id: string;
  ordinal: number;
  symbol: string | null;
  metric: string | null;
  value: string | null;
  as_of: string | null;
  endpoint: string | null;
  params: string | null;
  note: string | null;
}

export type SegmentKind =
  | "header"
  | "brief"
  | "decision"
  | "ledger"
  | "tool"
  | "verdict"
  | "guardrail"
  | "round"
  | "note"
  | "other";

export interface TranscriptSegment {
  ordinal: number;
  kind: SegmentKind;
  /** Short UI label chosen server-side, e.g. "Keputusan Jev". */
  label: string;
  /** The heading exactly as written in the file. */
  title: string;
  /** Markdown body, heading excluded. */
  body: string;
  /** Tool name for kind "tool", else null. */
  tool: string | null;
  /** One line of body text, for the collapsed row. */
  summary: string;
  /** Ordinals of the evidence rows this segment produced. */
  evidence_ordinals: number[];
}

export interface CheckDetail extends CheckSummary {
  claim_results: ClaimResult[];
  evidence: EvidenceRow[];
  changes: Change[];
  transcript?: string;
  /** Present only once the check has written its verdict. */
  finished?: boolean;
  /** The transcript split into labelled sections, decoded server-side. */
  transcript_segments?: TranscriptSegment[];
  /** Base URL the `/v2/...` evidence endpoints belong to. */
  sectors_base?: string;
}

export interface QueueRow {
  id: string;
  symbol: string;
  company_name: string | null;
  statement: string;
  status: ThesisStatus;
  confidence: number | null;
  watch: boolean;
  claims: number;
  last_checked_at: string | null;
  watermark: string | null;
  last_check: CheckSummary | null;
  changes: Change[];
  subject_type?: "equity" | "commodity";
}

export interface ThesisDetail {
  id: string;
  symbol: string;
  company_name: string | null;
  statement: string;
  translation: string | null;
  horizon: string | null;
  sector: string | null;
  sub_sector: string | null;
  source: string;
  watch: number;
  status: ThesisStatus;
  confidence: number | null;
  created_at: string;
  last_checked_at: string | null;
  watermark: string | null;
  claims: Claim[];
  last_check: CheckSummary | null;
  recent_changes: Change[];
  checks: CheckSummary[];
  latest?: CheckDetail;
  subject_type?: "equity" | "commodity";
}

export interface Notification {
  id: string;
  thesis_id: string;
  check_id: string | null;
  created_at: string;
  severity: string;
  title: string | null;
  body: string | null;
  read: number;
  symbol: string;
  statement: string;
}

export interface JobEvent {
  at: string;
  kind: string;
  index?: number;
  [key: string]: unknown;
}

export interface Job {
  kind: string;
  state: "running" | "done" | "error";
  started_at: string;
  finished_at?: string;
  events: JobEvent[];
  result: unknown;
  error: string | null;
  symbol?: string | null;
  thesis_id?: string | null;
  count?: number;
}

export interface Stats {
  store: {
    theses: number;
    by_status: Record<string, number>;
    checks: number;
    check_credits: number;
    watched: number;
    unread: number;
  };
  credits: {
    calls: number;
    network_calls: number;
    cached_calls: number;
    credits_spent: number;
    by_endpoint: Record<string, number>;
  };
  engine: Record<string, { available: boolean; detail: string; model?: string }>;
  jev: { available: boolean; model: string | null };
  schedule: Schedule;
  job: Job | null;
}

/** The schedule and its recent deliveries, published by `GET /api/stats`. */
export interface Schedule {
  next: string | null;
  when: string;
  days: string;
  tz: string;
  running: boolean;
  email_configured: boolean;
  digests: DigestRun[];
}

export interface DigestRun {
  at: string;
  checked: number;
  changed: number;
  emailed: boolean;
  subject: string | null;
  error: string | null;
  reason?: string;
  note?: string;
  to?: string[];
}

export interface Decomposition {
  mode: string;
  claims: Array<Record<string, unknown>>;
  unresolved: Array<{ text: string; reason: string }>;
  engine_error?: string;
}

export interface Draft {
  symbol: string;
  company_name: string | null;
  statement: string;
  horizon: string;
  evidence: Record<string, number | string | null>;
  generated: boolean;
}

/** The response of `GET /api/draft`, including the names it refused to draft. */
export interface DraftResponse {
  sub_sector: string;
  drafts: Draft[];
  skipped: Array<{ symbol: string; reason: string }>;
  credits: number;
  note: string;
}

export interface Commodity {
  name: string;
  data_points: number;
  earliest_date: string;
  latest_date: string;
  stale_days: number;
}