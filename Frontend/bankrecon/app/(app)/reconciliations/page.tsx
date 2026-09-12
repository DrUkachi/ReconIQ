import { redirect } from "next/navigation";
import { ReconciliationDashboard } from "@/app/components/dashboard/reconciliation-dashboard";
import { auth0 } from "@/lib/auth0";

export default async function ReconciliationsPage() {
  const session = await auth0.getSession();

  if (!session) {
    redirect("/auth/login");
  }

  return <ReconciliationDashboard />;
}
