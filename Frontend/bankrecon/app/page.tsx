export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_#ecfeff_0%,_#f8fafc_35%,_#e2e8f0_100%)] px-4 py-10">
      <section className="w-full max-w-4xl rounded-3xl border border-slate-200 bg-white/90 p-10 shadow-[0_20px_60px_rgba(15,23,42,0.12)] backdrop-blur-sm">
        <div className="flex flex-col gap-6 text-center md:text-left">
          <span className="inline-flex w-fit self-center rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700 md:self-start">
            BankRecon
          </span>

          <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
            Welcome to BankRecon
          </h1>

          <p className="max-w-2xl text-base leading-7 text-slate-600 sm:text-lg">
            Reconcile transactions with confidence, review exceptions faster, and bring
            clean financial visibility into every workflow.
          </p>

          <div className="flex flex-col gap-3 pt-2 sm:flex-row">
            <a
              href="/auth"
              className="inline-flex items-center justify-center rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Login / Create account
            </a>
          </div>
        </div>
      </section>
    </main>
  );
}
