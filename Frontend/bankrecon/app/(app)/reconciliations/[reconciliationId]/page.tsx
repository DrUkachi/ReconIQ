import { ReconciliationDetailView } from "@/app/components/dashboard/reconciliation-detail";
import {
  getCase,
  getCases,
  getReconciliation,
  getReconciliationAudit,
  getReconciliationTransactions,
  getTransaction,
  requireSession,
} from "@/app/lib/server-api";

export default async function ReconciliationDetailPage({
  params,
}: {
  params?: Promise<{ reconciliationId?: string }> | { reconciliationId?: string };
}) {
  const session = await requireSession();
  const resolvedParams = params instanceof Promise ? await params : params;
  const reconciliationId = resolvedParams?.reconciliationId ?? "";

  const [reconciliation, transactionPage, casePage, auditEvents] = await Promise.all([
    getReconciliation(reconciliationId),
    getReconciliationTransactions(reconciliationId),
    getCases(new URLSearchParams({ reconciliation_id: reconciliationId })),
    getReconciliationAudit(reconciliationId),
  ]);

  const [transactions, cases] = await Promise.all([
    Promise.all(transactionPage.items.map((item) => getTransaction(item.id))),
    Promise.all(casePage.items.map((item) => getCase(item.id))),
  ]);

  return (
    <ReconciliationDetailView
      session={session}
      reconciliation={reconciliation}
      transactions={transactions}
      cases={cases}
      auditEvents={auditEvents}
    />
  );
}
