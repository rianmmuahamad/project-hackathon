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
  verdict: ThesisStatus;
  confidence: number | null;
  summary: string | null;
  engine: string | null;
  model: string | null;
  credits: number;
  tool_calls: number;
  transcript_path: string | null;
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

export interface CheckDetail extends CheckSummary {
  claim_results: ClaimResult[];
  evidence: EvidenceRow[];
  changes: Change[];
  transcript?: string;
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
  job: Job | null;
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