"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { formatDate, formatMoney, formatPeriod, titleize } from "@/app/lib/format";
import type {
  CaseSummary,
  ReconciliationSummary,
  SessionData,
  SettingsOut,
} from "@/app/lib/types";

type DashboardProps = {
  session: SessionData;
  reconciliations: ReconciliationSummary[];
  cases: CaseSummary[];
  settings: SettingsOut;
};

function StatCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-3 text-3xl font-bold text-slate-900">{value}</p>
      <p className="mt-2 text-sm text-slate-600">{detail}</p>
    </div>
  );
}

function StatePill({ value }: { value: string }) {
  const tone =
    value === "AWAITING_ACTION"
      ? "bg-amber-50 text-amber-700 ring-amber-200"
      : value === "COMPLETE"
        ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
        : value === "MATCHING"
          ? "bg-cyan-50 text-cyan-700 ring-cyan-200"
          : "bg-slate-100 text-slate-700 ring-slate-200";

  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${tone}`}>
      {titleize(value)}
    </span>
  );
}

export function ReconciliationDashboard({
  session,
  reconciliations,
  cases,
  settings,
}: DashboardProps) {
  const [searchTerm, setSearchTerm] = useState("");

  const filteredReconciliations = useMemo(() => {
    const value = searchTerm.trim().toLowerCase();
    if (!value) return reconciliations;
    return reconciliations.filter((item) =>
      [item.account_last4, item.currency, item.state]
        .join(" ")
        .toLowerCase()
        .includes(value),
    );
  }, [reconciliations, searchTerm]);

  const matchedRows = reconciliations.reduce((total, item) => total + item.matched, 0);
  const reviewRows = reconciliations.reduce((total, item) => total + item.review, 0);
  const openCases = cases.filter((item) => item.state !== "CLOSED").length;

  return (
    <main className="space-y-6">
      <header className="rounded-[28px] border border-slate-200 bg-[linear-gradient(135deg,_#0f172a,_#111827_45%,_#164e63)] p-6 text-white shadow-[0_24px_70px_rgba(15,23,42,0.18)]">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">
              Live workspace
            </p>
            <h2 className="mt-2 text-3xl font-bold">Reconciliation control center</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
              Signed in as {session.user.display_name}. Upload a bank statement and ledger, review
              the matcher output, and work exceptions directly from the backend data model.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Link
              href="/reconciliations/new"
              className="inline-flex items-center justify-center rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-slate-900 transition hover:bg-slate-100"
            >
              Start new reconciliation
            </Link>
            <Link
              href="/settings"
              className="inline-flex items-center justify-center rounded-xl border border-white/20 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              Review settings
            </Link>
          </div>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Reconciliations"
          value={reconciliations.length.toString()}
          detail={`${filteredReconciliations.length} visible in the current view`}
        />
        <StatCard
          label="Matched rows"
          value={matchedRows.toString()}
          detail="Auto and confirmed matches across all runs"
        />
        <StatCard
          label="Needs review"
          value={reviewRows.toString()}
          detail="Review-band matches waiting on an approver"
        />
        <StatCard
          label="Open cases"
          value={openCases.toString()}
          detail={`Approval threshold ${formatMoney(settings.approval_value_threshold)}`}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
        <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h3 className="text-xl font-semibold text-slate-900">Reconciliations</h3>
              <p className="text-sm text-slate-500">
                Live summaries from the backend reconciliation engine.
              </p>
            </div>
            <input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Filter by account, currency, or state"
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-cyan-500 focus:bg-white md:max-w-xs"
            />
          </div>

          {filteredReconciliations.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
              No reconciliations match this filter yet.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-slate-500">
                  <tr>
                    <th className="pb-3 pr-4 font-medium">Period</th>
                    <th className="pb-3 pr-4 font-medium">Account</th>
                    <th className="pb-3 pr-4 font-medium">State</th>
                    <th className="pb-3 pr-4 font-medium">Rows</th>
                    <th className="pb-3 pr-4 font-medium">Open cases</th>
                    <th className="pb-3 pr-4 font-medium">Risk</th>
                    <th className="pb-3 font-medium">Opened</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredReconciliations.map((item) => (
                    <tr key={item.id} className="border-t border-slate-100 align-top">
                      <td className="py-3 pr-4">
                        <Link
                          href={`/reconciliations/${item.id}`}
                          className="font-semibold text-slate-900 transition hover:text-cyan-700"
                        >
                          {formatPeriod(item.period_start, item.period_end)}
                        </Link>
                        <div className="mt-1 text-xs text-slate-500">{item.currency}</div>
                      </td>
                      <td className="py-3 pr-4 font-medium text-slate-700">
                        •••• {item.account_last4}
                      </td>
                      <td className="py-3 pr-4">
                        <StatePill value={item.state} />
                      </td>
                      <td className="py-3 pr-4 text-slate-600">
                        {item.matched}/{item.total_rows} matched
                      </td>
                      <td className="py-3 pr-4 text-slate-600">{item.open_cases}</td>
                      <td className="py-3 pr-4 text-slate-600">
                        {formatMoney(item.value_at_risk)}
                      </td>
                      <td className="py-3 text-slate-600">{formatDate(item.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-xl font-semibold text-slate-900">Exception queue</h3>
            <p className="mt-1 text-sm text-slate-500">
              Open cases grouped by the deterministic exception engine.
            </p>

            <div className="mt-4 space-y-3">
              {cases.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                  No cases yet. Upload a reconciliation to generate review work.
                </div>
              ) : (
                cases.slice(0, 6).map((item) => (
                  <div key={item.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{item.title}</p>
                        <p className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">
                          {titleize(item.type)}
                        </p>
                      </div>
                      <StatePill value={item.state} />
                    </div>
                    <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
                      <span>{formatMoney(item.value_at_risk)}</span>
                      <span>{item.priority}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-xl font-semibold text-slate-900">Workspace rules</h3>
            <div className="mt-4 space-y-3 text-sm text-slate-600">
              <div className="rounded-2xl bg-slate-50 p-4">
                Auto-match threshold: <span className="font-semibold text-slate-900">{settings.auto_match_threshold}</span>
              </div>
              <div className="rounded-2xl bg-slate-50 p-4">
                Review floor: <span className="font-semibold text-slate-900">{settings.review_floor}</span>
              </div>
              <div className="rounded-2xl bg-slate-50 p-4">
                Listener threshold: <span className="font-semibold text-slate-900">{settings.listener_threshold}</span>
              </div>
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
