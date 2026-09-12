export default async function ExceptionDetailPage({
  params,
}: {
  params?: Promise<{ exceptionId?: string }> | { exceptionId?: string };
}) {
  const resolvedParams = params instanceof Promise ? await params : params;
  const exceptionId = resolvedParams?.exceptionId ?? "unknown";

  return (
    <main className="space-y-4">
      <h1 className="text-3xl font-bold text-slate-900">Exception</h1>
      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-slate-600">Exception ID: {exceptionId}</p>
      </section>
    </main>
  );
}
