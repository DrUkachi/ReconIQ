type AuthMode = "login" | "signup";

export function AuthCard({ mode: initialMode = "login" }: { mode?: AuthMode }) {
  const isLogin = initialMode === "login";
  const authHref = isLogin
    ? "/auth/login?returnTo=/auth/complete"
    : "/auth/login?screen_hint=signup&returnTo=/auth/complete";

  return (
    <div className="w-full max-w-md overflow-hidden rounded-[28px] border border-slate-200 bg-white/90 shadow-[0_24px_70px_rgba(15,23,42,0.14)] backdrop-blur-sm">
      <div className="relative overflow-hidden border-b border-slate-200 bg-[linear-gradient(135deg,_#0f172a,_#111827_42%,_#0f172a)] px-7 py-7 text-white">
        <div className="absolute -right-10 -top-10 h-28 w-28 rounded-full bg-cyan-400/20 blur-2xl" />
        <div className="absolute bottom-0 left-0 h-20 w-20 rounded-full bg-violet-500/20 blur-2xl" />

        <div className="relative">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-300 via-cyan-400 to-cyan-600 text-lg font-black text-slate-950 shadow-lg shadow-cyan-500/30">
              R
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-slate-300">RekonIQ</p>
              <h1 className="text-2xl font-bold">{isLogin ? "Welcome back" : "Create workspace access"}</h1>
            </div>
          </div>

          <p className="max-w-xs text-sm leading-6 text-slate-300">
            {isLogin
              ? "Use Auth0 to sign in with your work identity, then we will attach that session to your RekonIQ workspace."
              : "Use Auth0 to create or sign in to your account, then we will attach it to your RekonIQ workspace."}
          </p>
        </div>
      </div>

      <div className="space-y-6 px-7 py-7">
        <div className="grid grid-cols-2 rounded-2xl border border-slate-200 bg-slate-100 p-1">
          <a
            href="/login"
            className={`rounded-xl px-3 py-2.5 text-sm font-semibold transition ${
              isLogin ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            Login
          </a>
          <a
            href="/signup"
            className={`rounded-xl px-3 py-2.5 text-sm font-semibold transition ${
              !isLogin ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            Sign up
          </a>
        </div>

        <div className="rounded-2xl border border-cyan-100 bg-cyan-50 p-3 text-xs leading-5 text-slate-600">
          Auth0 verifies the identity. After login, RekonIQ creates or reuses the matching backend
          workspace user and keeps the backend session as the app&apos;s source of truth.
        </div>

        <a
          href={authHref}
          className="w-full rounded-xl bg-gradient-to-r from-slate-900 via-slate-800 to-cyan-700 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-cyan-500/10 transition hover:opacity-95 focus:outline-none focus:ring-4 focus:ring-cyan-200 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLogin ? "Continue with Auth0" : "Create account with Auth0"}
        </a>
      </div>
    </div>
  );
}
