import { ReconciliationDashboard } from "@/app/components/dashboard/reconciliation-dashboard";
import {
  getCases,
  getReconciliations,
  getSettings,
  requireSession,
} from "@/app/lib/server-api";

export default async function ReconciliationsPage() {
  const session = await requireSession();
  const [reconciliations, casePage, settings] = await Promise.all([
    getReconciliations(),
    getCases(),
    getSettings(),
  ]);

  return (
    <ReconciliationDashboard
      session={session}
      reconciliations={reconciliations}
      cases={casePage.items}
      settings={settings}
    />
  );
}
