"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { formatDate, formatDateTime, formatMoney, formatPeriod, titleize } from "@/app/lib/format";
import type { TransactionListPage } from "@/app/lib/types";

const MATCH_STATUSES = ["AUTO", "CONFIRMED", "REVIEW", "IN_CASE", "UNMATCHED"];
const PAGE_SIZES = [10, 25, 50, 100];

type Props = {
  data: TransactionListPage;
  // The sanitized query the server fetched with; the source of truth for every control.
  query: string;
};

function hrefWith(query: string, changes: Record<string, string | null>) {
  const params = new URLSearchParams(query);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === "") params.delete(key);
    else params.set(key, value);
  }
  // Any change other than the page itself starts again from the first page.
  if (!("page" in changes)) params.delete("page");
  if (params.get("page") === "1") params.delete("page");
  const text = params.toString();
  return text ? `/transactions?${text}` : "/transactions";
}

// 1 … 4 5 [6] 7 8 … 20
function pageWindow(current: number, pages: number): (number | "gap")[] {
  const wanted = new Set([1, pages, current - 2, current - 1, current, current + 1, current + 2]);
  const numbers = [...wanted].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const result: (number | "gap")[] = [];
  numbers.forEach((n, index) => {
    if (index > 0 && n - numbers[index - 1] > 1) result.push("gap");
    result.push(n);
  });
  return result;
}

function Pill({ value, tone }: { value: string; tone: "slate" | "cyan" | "amber" | "rose" | "emerald" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700 ring-slate-200",
    cyan: "bg-cyan-50 text-cyan-700 ring-cyan-200",
    amber: "bg-amber-50 text-amber-700 ring-amber-200",
    rose: "bg-rose-50 text-rose-700 ring-rose-200",
    emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  };
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${tones[tone]}`}>
      {value}
    </span>
  );
}

function matchTone(status: string) {
  if (status === "AUTO" || status === "CONFIRMED") return "emerald" as const;
  if (status === "REVIEW") return "amber" as const;
  if (status === "IN_CASE") return "rose" as const;
  return "slate" as const;
}

export function TransactionsTable({ data, query }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const params = new URLSearchParams(query);
  const [search, setSearch] = useState(params.get("q") ?? "");

  const resolution = params.get("resolution_status");
  const counts = data.resolution_counts;
  const allCount = (counts.PENDING ?? 0) + (counts.RESOLVED ?? 0);
  const firstRow = data.total === 0 ? 0 : (data.page - 1) * data.page_size + 1;
  const lastRow = Math.min(data.page * data.page_size, data.total);

  function go(changes: Record<string, string | null>) {
    startTransition(() => router.push(hrefWith(query, changes), { scroll: false }));
  }

  const tabs = [
    { label: "All", value: null, count: allCount },
    { label: "Pending", value: "PENDING", count: counts.PENDING ?? 0 },
    { label: "Resolved", value: "RESOLVED", count: counts.RESOLVED ?? 0 },
  ];

  return (
    <main className="space-y-6">
      <header className="rounded-[28px] border border-slate-200 bg-[linear-gradient(135deg,_#0f172a,_#111827_45%,_#164e63)] p-6 text-white shadow-[0_24px_70px_rgba(15,23,42,0.18)]">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">
          Every statement line
        </p>
        <h2 className="mt-2 text-3xl font-bold">Transactions</h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
          All bank transactions across your reconciliations, including those run from Slack, with
          their match result, Resolution Status and the case each open item belongs to.
        </p>
      </header>

      <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Resolution status">
            {tabs.map((tab) => {
              const active = (tab.value ?? null) === (resolution ?? null);
              return (
                <button
                  key={tab.label}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => go({ resolution_status: tab.value })}
                  className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${
                    active
                      ? "bg-slate-900 text-white"
                      : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {tab.label}
                  <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${active ? "bg-white/15" : "bg-slate-100"}`}>
                    {tab.count}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <form
              className="flex flex-1 gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                go({ q: search.trim() || null });
              }}
            >
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search narration, reference or counterparty"
                aria-label="Search transactions"
                maxLength={100}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
              />
              <button
                type="submit"
                className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700"
              >
                Search
              </button>
            </form>

            <div className="flex flex-wrap gap-2">
              <select
                aria-label="Match status"
                value={params.get("status") ?? ""}
                onChange={(event) => go({ status: event.target.value || null })}
                className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700"
              >
                <option value="">Any match status</option>
                {MATCH_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {titleize(status)}
                  </option>
                ))}
              </select>
              <select
                aria-label="Currency"
                value={params.get("currency") ?? ""}
                onChange={(event) => go({ currency: event.target.value || null })}
                className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700"
              >
                <option value="">All currencies</option>
                {data.currencies.map((currency) => (
                  <option key={currency} value={currency}>
                    {currency}
                  </option>
                ))}
              </select>
              <select
                aria-label="Rows per page"
                value={String(data.page_size)}
                onChange={(event) => go({ page_size: event.target.value })}
                className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700"
              >
                {PAGE_SIZES.map((size) => (
                  <option key={size} value={size}>
                    {size} per page
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className={`mt-5 transition-opacity ${isPending ? "opacity-50" : ""}`} aria-busy={isPending}>
          {data.items.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
              No transactions match these filters.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-slate-200 text-slate-500">
                  <tr>
                    <th className="pb-3 pr-4 font-medium">Date</th>
                    <th className="pb-3 pr-4 font-medium">Reconciliation</th>
                    <th className="pb-3 pr-4 font-medium">Details</th>
                    <th className="pb-3 pr-4 text-right font-medium">Amount</th>
                    <th className="pb-3 pr-4 font-medium">Match</th>
                    <th className="pb-3 pr-4 font-medium">Resolution</th>
                    <th className="pb-3 font-medium">Case</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.items.map((item) => (
                    <tr key={item.id} className="align-top">
                      <td className="whitespace-nowrap py-3 pr-4 text-slate-700">{formatDate(item.value_date)}</td>
                      <td className="py-3 pr-4">
                        <Link
                          href={`/reconciliations/${item.reconciliation_id}`}
                          className="font-semibold text-cyan-700 hover:text-cyan-900"
                        >
                          {item.currency} · {item.account_last4}
                        </Link>
                        <p className="whitespace-nowrap text-xs text-slate-500">
                          {formatPeriod(item.period_start, item.period_end)}
                        </p>
                      </td>
                      <td className="max-w-md py-3 pr-4">
                        <p className="text-slate-800">{item.narration || "No narration"}</p>
                        <p className="mt-1 text-xs text-slate-500">
                          {item.reference || "No reference"}
                          {item.counterparty ? ` · ${item.counterparty}` : ""}
                        </p>
                      </td>
                      <td className="whitespace-nowrap py-3 pr-4 text-right">
                        <p className={`font-semibold ${item.direction === "CREDIT" ? "text-emerald-700" : "text-slate-900"}`}>
                          {item.direction === "CREDIT" ? "+" : "−"}
                          {formatMoney(item.amount)}
                        </p>
                        <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{item.direction}</p>
                      </td>
                      <td className="py-3 pr-4">
                        <Pill value={titleize(item.status)} tone={matchTone(item.status)} />
                      </td>
                      <td className="py-3 pr-4">
                        <span
                          title={
                            item.resolution_status === "RESOLVED"
                              ? [item.resolution_note, item.resolved_at ? formatDateTime(item.resolved_at) : null]
                                  .filter(Boolean)
                                  .join(" · ")
                              : undefined
                          }
                        >
                          <Pill
                            value={item.resolution_status === "RESOLVED" ? "Resolved" : "Pending"}
                            tone={item.resolution_status === "RESOLVED" ? "emerald" : "amber"}
                          />
                        </span>
                      </td>
                      <td className="py-3">
                        {item.case_type ? (
                          <div className="space-y-1">
                            <p className="whitespace-nowrap font-medium text-slate-800">{titleize(item.case_type)}</p>
                            <p className="text-xs text-slate-500">
                              {item.case_state ? titleize(item.case_state) : ""}
                              {item.case_routed_team ? ` · ${titleize(item.case_routed_team)}` : ""}
                            </p>
                            {item.case_permalink ? (
                              <a
                                href={item.case_permalink}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs font-semibold text-cyan-700 hover:text-cyan-900"
                              >
                                Open Slack thread ↗
                              </a>
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-400">None</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <nav
          className="mt-5 flex flex-col gap-3 border-t border-slate-100 pt-4 text-sm sm:flex-row sm:items-center sm:justify-between"
          aria-label="Pagination"
        >
          <p className="text-slate-500">
            Showing <span className="font-semibold text-slate-800">{firstRow}</span>–
            <span className="font-semibold text-slate-800">{lastRow}</span> of{" "}
            <span className="font-semibold text-slate-800">{data.total}</span>
          </p>
          <div className="flex flex-wrap items-center gap-1">
            <PageLink query={query} page={data.page - 1} disabled={data.page <= 1} label="Previous" />
            {pageWindow(data.page, data.pages).map((entry, index) =>
              entry === "gap" ? (
                <span key={`gap-${index}`} className="px-2 text-slate-400">
                  …
                </span>
              ) : (
                <PageLink key={entry} query={query} page={entry} current={entry === data.page} label={String(entry)} />
              ),
            )}
            <PageLink query={query} page={data.page + 1} disabled={data.page >= data.pages} label="Next" />
          </div>
        </nav>
      </section>
    </main>
  );
}

function PageLink({
  query,
  page,
  label,
  current = false,
  disabled = false,
}: {
  query: string;
  page: number;
  label: string;
  current?: boolean;
  disabled?: boolean;
}) {
  const base = "min-w-9 rounded-lg px-3 py-1.5 text-center font-medium";
  if (disabled) {
    return <span className={`${base} cursor-not-allowed text-slate-300`}>{label}</span>;
  }
  if (current) {
    return (
      <span aria-current="page" className={`${base} bg-slate-900 text-white`}>
        {label}
      </span>
    );
  }
  return (
    <Link href={hrefWith(query, { page: String(page) })} scroll={false} className={`${base} text-slate-600 hover:bg-slate-100`}>
      {label}
    </Link>
  );
}
