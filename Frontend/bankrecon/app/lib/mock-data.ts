import type {
  AuditEvent,
  ExceptionItem,
  ReconciliationRow,
  SlackSetting,
  TransactionMatch,
} from "./types";

export const reconciliationRows: ReconciliationRow[] = [
  {
    id: "REC-1042",
    period: "Jun 2026",
    customer: "Northwind Labs",
    totalValue: 482750,
    matchedValue: 474600,
    exceptions: 3,
    status: "in_review",
    updatedAt: "12 min ago",
    risk: "Medium",
  },
  {
    id: "REC-1039",
    period: "Jun 2026",
    customer: "Cinder & Co",
    totalValue: 318420,
    matchedValue: 318420,
    exceptions: 0,
    status: "matched",
    updatedAt: "1 hour ago",
    risk: "Low",
  },
  {
    id: "REC-1031",
    period: "May 2026",
    customer: "Aster Bank",
    totalValue: 915600,
    matchedValue: 868200,
    exceptions: 9,
    status: "exception",
    updatedAt: "2 hours ago",
    risk: "High",
  },
  {
    id: "REC-1028",
    period: "May 2026",
    customer: "Blue Harbor",
    totalValue: 640200,
    matchedValue: 0,
    exceptions: 2,
    status: "pending",
    updatedAt: "3 hours ago",
    risk: "Medium",
  },
];

export const transactionMatches: TransactionMatch[] = [
  {
    id: "TX-2001",
    reference: "BACS-20491",
    amount: 14250,
    date: "2026-06-11",
    customer: "Northwind Labs",
    matchScore: 97,
    evidence: ["Invoice INV-8841", "Statement line 44", "Customer reference matches"],
    status: "Auto-match",
  },
  {
    id: "TX-2002",
    reference: "WIRE-77104",
    amount: 22500,
    date: "2026-06-12",
    customer: "Northwind Labs",
    matchScore: 89,
    evidence: ["Same settlement date", "Customer account suffix 2049", "Amount variance 0.4%"],
    status: "Manual review",
  },
  {
    id: "TX-2003",
    reference: "ACH-91002",
    amount: 35680,
    date: "2026-06-12",
    customer: "Aster Bank",
    matchScore: 64,
    evidence: ["Statement reference mismatch", "Duplicate receipt flagged", "Alternative account ID"],
    status: "Exception",
  },
];

export const exceptionQueue: ExceptionItem[] = [
  {
    id: "EX-445",
    customer: "Aster Bank",
    reason: "Missing remittance advice",
    amount: 35680,
    priority: "High",
    escalation: "Escalated",
    requiredReason: "Customer dispute note required",
  },
  {
    id: "EX-448",
    customer: "Blue Harbor",
    reason: "Partial settlement mismatch",
    amount: 14320,
    priority: "Medium",
    escalation: "Queue",
    requiredReason: "Finance approval required",
  },
  {
    id: "EX-451",
    customer: "Northwind Labs",
    reason: "Duplicate credit entry",
    amount: 6850,
    priority: "Low",
    escalation: "Resolved",
    requiredReason: "No further action required",
  },
];

export const auditTrail: AuditEvent[] = [
  {
    id: "AUD-911",
    actor: "A. Patel",
    action: "Matched payment batch",
    time: "09:12",
    detail: "Matched 12 transactions against June statement batch 6A.",
    type: "system",
  },
  {
    id: "AUD-912",
    actor: "S. Grant",
    action: "Flagged variance",
    time: "09:41",
    detail: "Escalated transaction TX-2003 due to remittance mismatch.",
    type: "review",
  },
  {
    id: "AUD-913",
    actor: "Ops Bot",
    action: "Slack alert sent",
    time: "10:03",
    detail: "Posted exception summary to #recon-ops-alerts.",
    type: "escalation",
  },
  {
    id: "AUD-914",
    actor: "R. Chen",
    action: "Approved exception closure",
    time: "11:12",
    detail: "Customer dispute note reviewed and exception moved to resolved.",
    type: "review",
  },
];

export const slackSettings: SlackSetting[] = [
  {
    channel: "#recon-ops-alerts",
    enabled: true,
    alerts: ["Exception escalations", "Daily summary", "Low match confidence"],
  },
  {
    channel: "#finance-approvals",
    enabled: false,
    alerts: ["Variance approvals", "Manual match decisions"],
  },
];
