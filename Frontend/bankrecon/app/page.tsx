export default function Home() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_#ecfeff_0%,_#f8fafc_35%,_#e2e8f0_100%)] px-4 py-8 text-slate-900 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-slate-900 via-cyan-700 to-cyan-500 text-lg font-bold text-white shadow-lg shadow-cyan-200/50">
              R
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">RekonIQ</p>
            </div>
          </div>

          <nav className="hidden items-center gap-6 text-sm text-slate-600 md:flex">
            <a href="#features" className="transition hover:text-slate-900">Features</a>
            <a href="#why" className="transition hover:text-slate-900">Why it works</a>
            <a href="#security" className="transition hover:text-slate-900">Security</a>
          </nav>

          <div className="flex items-center gap-3">
            <a
              href="/auth/login"
              className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Login
            </a>
            <a
              href="/auth/login?screen_hint=signup"
              className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Register
            </a>
          </div>
        </header>

        <section className="grid items-center gap-10 pb-12 pt-6 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-8">
            <span className="inline-flex rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-700">
              AI reconciliation teammate
            </span>

            <div className="space-y-5">
              <h1 className="max-w-xl text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl">
                Reconcile faster. Resolve exceptions with confidence.
              </h1>
              <p className="max-w-xl text-lg leading-8 text-slate-600">
                RekonIQ turns bank-statement reconciliation into a tracked, collaborative workflow,
                helping finance teams match payments, explain mismatches, and close exceptions in
                real time.
              </p>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row">
              <a
                href="/auth/login?screen_hint=signup"
                className="inline-flex items-center justify-center rounded-xl bg-slate-900 px-6 py-3 text-base font-semibold text-white transition hover:bg-slate-800"
              >
                Get Started
              </a>
              <a
                href="/auth/login"
                className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-6 py-3 text-base font-semibold text-slate-700 transition hover:bg-slate-50"
              >
                Login
              </a>
              <a
                href="/auth/login?screen_hint=signup"
                className="inline-flex items-center justify-center rounded-xl border border-cyan-200 bg-cyan-50 px-6 py-3 text-base font-semibold text-cyan-700 transition hover:bg-cyan-100"
              >
                Register
              </a>
            </div>

            <div className="flex flex-wrap items-center gap-6 pt-2 text-sm text-slate-500">
              <span>94.6% match accuracy</span>
              <span>•</span>
              <span>Slack-first workflow</span>
              <span>•</span>
              <span>Audit-ready activity trail</span>
            </div>
          </div>

          <div className="relative">
            <div className="absolute -left-4 top-8 h-28 w-28 rounded-full bg-cyan-200/70 blur-3xl" />
            <div className="absolute -right-4 bottom-8 h-28 w-28 rounded-full bg-violet-200/70 blur-3xl" />

            <div className="relative overflow-hidden rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_25px_60px_rgba(15,23,42,0.12)]">
              <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-900">
                <div className="h-56 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.22),_transparent_50%),linear-gradient(135deg,_#0f172a,_#111827_45%,_#0f172a)] p-5 text-white">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-slate-300">June reconciliation</span>
                    <span className="rounded-full bg-emerald-500/20 px-2 py-1 text-xs font-medium text-emerald-300">
                      On track
                    </span>
                  </div>

                  <div className="mt-6 grid gap-3">
                    {[
                      { label: "Matched", value: "92.4%", tone: "text-emerald-300" },
                      { label: "Exceptions", value: "18", tone: "text-amber-300" },
                      { label: "Escalated", value: "4", tone: "text-cyan-300" },
                    ].map((stat) => (
                      <div key={stat.label} className="flex items-center justify-between rounded-xl bg-white/5 px-3 py-2.5 backdrop-blur-sm">
                        <span className="text-sm text-slate-300">{stat.label}</span>
                        <span className={`text-base font-semibold ${stat.tone}`}>{stat.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="mt-5 grid gap-3">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-slate-700">Top issue</span>
                    <span className="text-cyan-700">Needs review</span>
                  </div>
                  <p className="mt-2 text-sm text-slate-600">Missing remittance advice for 3 high-value payments.</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-slate-700">Slack update</span>
                    <span className="text-emerald-700">Live</span>
                  </div>
                  <p className="mt-2 text-sm text-slate-600">Assigned to finance ops and closed in-thread with evidence.</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="features" className="grid gap-6 py-16 md:grid-cols-3">
          {[
            {
              title: "Upload & match",
              text: "Parse statement PDFs and internal payment CSVs in one flow and score every line automatically.",
              icon: "⇄",
            },
            {
              title: "Exception workflow",
              text: "Capture unmatched items, assign ownership, escalate when needed, and resolve with required reasons.",
              icon: "◎",
            },
            {
              title: "Audit-ready trail",
              text: "Every match, action, escalation, and closure is timestamped and visible in one workspace.",
              icon: "▣",
            },
          ].map((feature) => (
            <div key={feature.title} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-cyan-50 text-lg font-bold text-cyan-700">
                {feature.icon}
              </div>
              <h3 className="text-xl font-semibold text-slate-900">{feature.title}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-600">{feature.text}</p>
            </div>
          ))}
        </section>

        <section id="why" className="rounded-3xl border border-slate-200 bg-slate-900 px-6 py-8 text-white md:px-8">
          <div className="grid gap-6 md:grid-cols-2 md:items-center">
            <div>
              <p className="text-sm font-medium uppercase tracking-[0.2em] text-cyan-300">Why teams use RekonIQ</p>
              <h2 className="mt-3 text-3xl font-bold">A workflow your finance team can trust.</h2>
            </div>
            <div className="space-y-4 text-slate-300">
              <p>• Reduce manual reconciliation effort across large statement batches.</p>
              <p>• Keep exception ownership visible and accountable.</p>
              <p>• Produce a clear audit trail without rebuilding history later.</p>
            </div>
          </div>
        </section>

        <section className="grid gap-6 py-16 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-3xl border border-slate-200 bg-white p-7 shadow-sm">
            <p className="text-sm font-medium uppercase tracking-[0.2em] text-cyan-700">Customer stories</p>
            <h3 className="mt-4 text-3xl font-bold text-slate-900">“We cut reconciliation time from days to hours.”</h3>
            <p className="mt-4 text-slate-600">
              “Our finance team now reviews exceptions in one place, with contextual notes and a clean
              record of every decision. It feels like having a dedicated reconciliation teammate.”
            </p>
            <div className="mt-6 flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-900 text-sm font-bold text-white">
                LW
              </div>
              <div>
                <p className="font-semibold text-slate-900">Lena Walker</p>
                <p className="text-sm text-slate-500">Finance Director, Northwind Labs</p>
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-[linear-gradient(135deg,_#ecfeff,_#f8fafc_55%,_#e0f2fe)] p-7 shadow-sm">
            <p className="text-sm font-medium uppercase tracking-[0.2em] text-cyan-700">Simple pricing</p>
            <div className="mt-4 flex items-end gap-3">
              <span className="text-4xl font-bold text-slate-900">$79</span>
              <span className="pb-1 text-slate-500">/month</span>
            </div>
            <ul className="mt-6 space-y-3 text-sm text-slate-700">
              <li>• Unlimited reconciliations</li>
              <li>• Slack-first workflow</li>
              <li>• Exception tracking and audit logs</li>
              <li>• Team collaboration tools</li>
            </ul>
            <a
              href="/auth/login?screen_hint=signup"
              className="mt-6 inline-flex items-center justify-center rounded-xl bg-cyan-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-cyan-500"
            >
              Try RekonIQ
            </a>
          </div>
        </section>

        <footer id="security" className="mt-16 border-t border-slate-200 pt-8 text-sm text-slate-600">
          <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-slate-900 via-cyan-700 to-cyan-500 text-sm font-bold text-white">
                R
              </div>
              <span className="font-semibold text-slate-800">RekonIQ</span>
            </div>

            <div className="flex flex-wrap items-center gap-6">
              <a href="#features" className="transition hover:text-slate-900">Features</a>
              <a href="#why" className="transition hover:text-slate-900">Why it works</a>
              <a href="/auth/login" className="transition hover:text-slate-900">Access app</a>
            </div>

            <p>© 2026 RekonIQ. Built for finance teams.</p>
          </div>
        </footer>
      </div>
    </main>
  );
}
