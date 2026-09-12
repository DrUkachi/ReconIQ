export default async function TransactionDetailPage({
  params,
}: {
  params?: Promise<{ transactionId?: string }> | { transactionId?: string };
}) {
  const resolvedParams = params instanceof Promise ? await params : params;
  const transactionId = resolvedParams?.transactionId ?? "unknown";

  return (
    <main className="space-y-4">
      <h1 className="text-3xl font-bold text-slate-900">Transaction</h1>
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-slate-600">Transaction ID: {transactionId}</p>
      </section>
    </main>
  );
}
