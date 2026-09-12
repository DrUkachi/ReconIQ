export default async function ReconciliationDetailPage({
  params,
}: {
  params?: Promise<{ reconciliationId?: string }> | { reconciliationId?: string };
}) {
  const resolvedParams = params instanceof Promise ? await params : params;
  const reconciliationId = resolvedParams?.reconciliationId ?? "unknown";

  return (
    <main className="space-y-4">
      <h1 className="text-3xl font-bold text-slate-900">Reconciliation</h1>
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-slate-600">ID: {reconciliationId}</p>
      </section>
    </main>
  );
}
