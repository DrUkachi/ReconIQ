export type ReconciliationStatus =
  | "matched"
  | "in_review"
  | "exception"
  | "pending";

export type AuditEvent = {
  id: string;
  actor: string;
  action: string;
  time: string;
  detail: string;
  type: "system" | "review" | "escalation";
};

export type ReconciliationRow = {
  id: string;
  period: string;
  customer: string;
  totalValue: number;
  matchedValue: number;
  exceptions: number;
  status: ReconciliationStatus;
  updatedAt: string;
  risk: "Low" | "Medium" | "High";
};

export type TransactionMatch = {
  id: string;
  reference: string;
  amount: number;
  date: string;
  customer: string;
  matchScore: number;
  evidence: string[];
  status: "Auto-match" | "Manual review" | "Exception";
};

export type ExceptionItem = {
  id: string;
  customer: string;
  reason: string;
  amount: number;
  priority: "High" | "Medium" | "Low";
  escalation: "Queue" | "Escalated" | "Resolved";
  requiredReason: string;
};

export type SlackSetting = {
  channel: string;
  enabled: boolean;
  alerts: string[];
};
