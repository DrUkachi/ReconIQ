import { AuthCard } from "../components/auth/auth-card";

export default function AuthPage({
  searchParams,
}: {
  searchParams?: Promise<{ auth_error?: string }>;
}) {
  const missingAuthConfig = searchParams ? (searchParams as any)?.auth_error === "missing_auth0_config" : false;

  return (
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_#ecfeff_0%,_#f8fafc_35%,_#e2e8f0_100%)] px-4 py-10">
      {missingAuthConfig ? (
        <div className="w-full max-w-xl rounded-3xl border border-amber-200 bg-white p-8 shadow-[0_20px_60px_rgba(15,23,42,0.12)]">
          <div className="mb-4 inline-flex rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-amber-700">
            Auth0 setup required
          </div>
          <h1 className="text-3xl font-bold text-slate-900">Login is not available yet</h1>
          <p className="mt-4 text-slate-600">
            Your Auth0 credentials are still using placeholders. Update the values in the project
            <span className="font-semibold text-slate-800"> .env.local </span>
            file with your real Auth0 tenant details, then restart the app.
          </p>
          <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
            Required values:
            <ul className="mt-3 list-disc space-y-2 pl-5">
              <li>AUTH0_DOMAIN</li>
              <li>AUTH0_CLIENT_ID</li>
              <li>AUTH0_CLIENT_SECRET</li>
              <li>AUTH0_SECRET</li>
            </ul>
          </div>
          <a
            href="/"
            className="mt-6 inline-flex items-center justify-center rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
          >
            Back to home
          </a>
        </div>
      ) : (
        <AuthCard mode="login" />
      )}
    </main>
  );
}
