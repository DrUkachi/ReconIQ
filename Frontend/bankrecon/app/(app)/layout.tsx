import type { ReactNode } from "react";
import Link from "next/link";

import { requireSession } from "@/app/lib/server-api";

export default async function AppLayout({ children }: { children: ReactNode }) {
  const session = await requireSession();

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_#ecfeff_0%,_#f8fafc_32%,_#e2e8f0_100%)] text-slate-900">
      <div className="mx-auto max-w-7xl p-4 md:p-6">
        <header className="mb-6 rounded-[28px] border border-slate-200 bg-white/90 p-5 shadow-[0_20px_60px_rgba(15,23,42,0.08)] backdrop-blur">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-slate-900 via-cyan-700 to-cyan-500 text-lg font-bold text-white">
                R
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-700">
                  {session.workspace.name}
                </p>
                <h1 className="text-2xl font-bold text-slate-900">RekonIQ Workspace</h1>
              </div>
            </div>

            <nav className="flex flex-wrap items-center gap-2 text-sm">
              <Link
                href="/reconciliations"
                className="rounded-xl px-3 py-2 font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
              >
                Reconciliations
              </Link>
              <Link
                href="/reconciliations/new"
                className="rounded-xl px-3 py-2 font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
              >
                New Run
              </Link>
              <Link
                href="/settings"
                className="rounded-xl px-3 py-2 font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
              >
                Settings
              </Link>
            </nav>

            <div className="flex items-center gap-3">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-right">
                <p className="text-sm font-semibold text-slate-900">{session.user.display_name}</p>
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                  {session.user.role}
                </p>
              </div>
              <Link
                href="/logout"
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                Sign out
              </Link>
            </div>
          </div>
        </header>

        {children}
      </div>
    </div>
  );
}
