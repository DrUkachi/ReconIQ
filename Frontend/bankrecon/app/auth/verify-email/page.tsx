export default function VerifyEmailPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_#ecfeff_0%,_#f8fafc_35%,_#e2e8f0_100%)] px-4 py-10">
      <div className="w-full max-w-md rounded-[28px] border border-slate-200 bg-white/90 p-8 shadow-[0_24px_70px_rgba(15,23,42,0.14)]">
        <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-cyan-700">RekonIQ</p>
        <h1 className="mt-2 text-2xl font-bold text-slate-900">Verify your email</h1>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          Check your inbox for the verification email from Auth0 and open the link. Then sign in
          again to reach your workspace.
        </p>
        <a
          href="/logout"
          className="mt-6 inline-flex w-full items-center justify-center rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
        >
          I have verified my email
        </a>
      </div>
    </main>
  );
}
