export type Role = "member" | "approver" | "owner";

export type Money = {
  minor: number;
  currency: string;
  display: string;
};

export type SessionUser = {
  id: string;
  display_name: string;
  email_masked: string | null;
  role: Role;
  slack_user_id: string;
};

export type Workspace = {
  id: string;
  name: string;
};

export type SessionData = {
  user: SessionUser;
  workspace: Workspace;
};

export type ReconciliationSummary = {
  id: string;
  account_last4: string;
  period_start: string;
  period_end: string;
  state: string;
  currency: string;
  total_rows: number;
  matched: number;
  review: number;
  in_case: number;
  unmatched: number;
  open_cases: number;
  value_at_risk: Money | null;
  created_at: string | null;
  completed_at: string | null;
};

export type StatementProvenance = {
  filename: string;
  content_sha256: string;
  page_count: number;
  extraction_method: string;
  confidence: number;
  inferred_date_format: string | null;
  balance_breaks: number;
  skipped_rows: number;
  warnings: string[];
};

export type ReconciliationDetail = ReconciliationSummary & {
  statement: StatementProvenance | null;
  completion_blockers: string[];
};

export type ScoreComponents = {
  amount: number;
  reference: number;
  date: number;
  counterparty: number;
  total: number;
};

export type CandidateOut = {
  payment_record_id: string;
  external_id: string;
  record_date: string;
  amount: Money;
  reference: string;
  counterparty: string;
  score: number;
  breakdown: ScoreComponents;
};

export type TransactionOut = {
  id: string;
  row_index: number;
  value_date: string;
  narration: string;
  reference: string;
  counterparty: string;
  amount: Money;
  direction: string;
  status: string;
  balance: Money | null;
  warnings: string[];
};

export type TransactionDetail = TransactionOut & {
  candidates: CandidateOut[];
  match_state: string | null;
  case_id: string | null;
};

export type EvidenceOut = {
  id: string;
  kind: string;
  author_slack_id: string | null;
  excerpt: string;
  permalink: string | null;
  matched_on: string[];
  score: number | null;
  verified: boolean;
  created_at: string | null;
};

export type ProposalOut = {
  id: string;
  reason_code: string;
  narrative: string;
  state: string;
  evidence_ids: string[];
  proposed_by: string | null;
  decided_by: string | null;
  decided_at: string | null;
  requires_approver: boolean;
};

export type CaseSummary = {
  id: string;
  type: string;
  state: string;
  priority: string;
  title: string;
  value_at_risk: Money;
  assignee_id: string | null;
  due_at: string | null;
  permalink: string | null;
  version: number;
};

export type CaseDetail = CaseSummary & {
  summary: string;
  reconciliation_id: string;
  transactions: TransactionOut[];
  evidence: EvidenceOut[];
  proposals: ProposalOut[];
  escalated_to: string | null;
  escalated_at: string | null;
};

export type Cursor = {
  next: string | null;
  has_more: boolean;
};

export type TransactionPage = {
  items: TransactionOut[];
  cursor: Cursor;
};

export type CasePage = {
  items: CaseSummary[];
  cursor: Cursor;
};

export type AuditEventOut = {
  id: string;
  action: string;
  actor_user_id: string | null;
  actor_slack_id: string | null;
  case_id: string | null;
  from_state: string | null;
  to_state: string | null;
  reason: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export type SettingsOut = {
  approval_value_threshold: Money;
  auto_match_threshold: number;
  review_floor: number;
  ambiguity_gap: number;
  date_window_days: number;
  listener_threshold: number;
  recon_channel_id: string | null;
};

export type ApiError = {
  code: string;
  message: string;
  details: Record<string, unknown>;
  correlation_id?: string;
};
