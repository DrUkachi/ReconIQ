"use client";

import Link from "next/link";
import { startTransition, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/app/lib/api";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatPeriod,
  titleize,
} from "@/app/lib/format";
import type {
  AuditEventOut,
  CaseDetail,
  ReconciliationDetail,
  SessionData,
  TransactionDetail,
} from "@/app/lib/types";

type ReconciliationDetailProps = {
  session: SessionData;
  reconciliation: ReconciliationDetail;
  transactions: TransactionDetail[];
  cases: CaseDetail[];
  auditEvents: AuditEventOut[];
};

function SummaryCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-3 text-3xl font-bold text-slate-900">{value}</p>
    </div>
  );
}

function Badge({
  value,
  tone = "slate",
}: {
  value: string;
  tone?: "slate" | "cyan" | "amber" | "rose" | "emerald";
}) {
  const styles = {
    slate: "bg-slate-100 text-slate-700",
    cyan: "bg-cyan-50 text-cyan-700",
    amber: "bg-amber-50 text-amber-700",
    rose: "bg-rose-50 text-rose-700",
    emerald: "bg-emerald-50 text-emerald-700",
  };

  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${styles[tone]}`}>
      {value}
    </span>
  );
}

export function ReconciliationDetailView({
  session,
  reconciliation,
  transactions,
  cases,
  auditEvents,
}: ReconciliationDetailProps) {
  const router = useRouter();
  const [searchTerm, setSearchTerm] = useState("");
  const [pendingDecisionId, setPendingDecisionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const filteredTransactions = useMemo(() => {
    const value = searchTerm.trim().toLowerCase();
    if (!value) return transactions;
    return transactions.filter((item) =>
      [item.narration, item.reference, item.counterparty, item.status]
        .join(" ")
        .toLowerCase()
        .includes(value),
    );
  }, [searchTerm, transactions]);

  const handleDecision = async (
    transactionId: string,
    paymentRecordId: string,
    decision: "confirm" | "reject",
  ) => {
    setPendingDecisionId(transactionId);
    setError(null);

    try {
      await apiFetch(`/api/backend/transactions/${transactionId}/decision`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          payment_record_id: paymentRecordId,
          decision,
        }),
      });
      startTransition(() => {
        router.refresh();
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save that decision.");
    } finally {
      setPendingDecisionId(null);
    }
  };

  return (
    <main className="space-y-6">
      <header className="rounded-[30px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">
              Reconciliation detail
            </p>
            <h1 className="mt-2 text-3xl font-bold text-slate-900">
              {formatPeriod(reconciliation.period_start, reconciliation.period_end)}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-600">
              <Badge value={`Account •••• ${reconciliation.account_last4}`} />
              <Badge value={titleize(reconciliation.state)} tone="cyan" />
              <Badge value={reconciliation.currency} tone="emerald" />
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            <a
              href={`/api/backend/reconciliations/${reconciliation.id}/audit.csv`}
              className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Export audit CSV
            </a>
            <Link
              href="/reconciliations"
              className="inline-flex items-center justify-center rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              Back to dashboard
            </Link>
          </div>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Matched" value={reconciliation.matched.toString()} />
        <SummaryCard label="Review" value={reconciliation.review.toString()} />
        <SummaryCard label="In case" value={reconciliation.in_case.toString()} />
        <SummaryCard label="Unmatched" value={reconciliation.unmatched.toString()} />
      </section>

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <section className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
        <div className="space-y-6">
          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-slate-900">Transactions</h2>
                <p className="text-sm text-slate-500">
                  Review the live matcher output and confirm any review-band candidates.
                </p>
              </div>
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Search narration, reference, or status"
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-cyan-500 focus:bg-white md:max-w-xs"
              />
            </div>

            <div className="space-y-4">
              {filteredTransactions.map((transaction) => {
                const candidate = transaction.candidates[0];
                const isPending = pendingDecisionId === transaction.id;
                return (
                  <div
                    key={transaction.id}
                    className="rounded-2xl border border-slate-200 bg-slate-50 p-4"
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">
                            Row {transaction.row_index}
                          </span>
                          <Badge
                            value={titleize(transaction.status)}
                            tone={transaction.status === "REVIEW" ? "amber" : "emerald"}
                          />
                          {transaction.case_id ? <Badge value="Linked case" tone="rose" /> : null}
                        </div>
                        <p className="text-sm text-slate-700">{transaction.narration}</p>
                        <div className="flex flex-wrap gap-4 text-xs uppercase tracking-[0.16em] text-slate-500">
                          <span>{formatDate(transaction.value_date)}</span>
                          <span>{transaction.reference || "No reference"}</span>
                          <span>{transaction.counterparty || "No counterparty"}</span>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-lg font-semibold text-slate-900">
                          {formatMoney(transaction.amount)}
                        </p>
                        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                          {transaction.direction}
                        </p>
                      </div>
                    </div>

                    {candidate ? (
                      <div className="mt-4 rounded-2xl border border-cyan-100 bg-white p-4">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div>
                            <p className="text-sm font-semibold text-slate-900">
                              Candidate record {candidate.external_id || candidate.payment_record_id}
                            </p>
                            <p className="mt-1 text-sm text-slate-600">
                              {candidate.counterparty || "No counterparty"} • {formatMoney(candidate.amount)} •{" "}
                              {formatDate(candidate.record_date)}
                            </p>
                          </div>
                          <Badge value={`Score ${candidate.score}`} tone="cyan" />
                        </div>
                        <div className="mt-3 grid gap-2 text-sm text-slate-600 md:grid-cols-2">
                          <div className="rounded-xl bg-slate-50 p-3">
                            Reference: <span className="font-medium text-slate-900">{candidate.reference || "None"}</span>
                          </div>
                          <div className="rounded-xl bg-slate-50 p-3">
                            Breakdown total: <span className="font-medium text-slate-900">{candidate.breakdown.total}</span>
                          </div>
                        </div>

                        {transaction.match_state === "REVIEW" && session.user.role !== "member" ? (
                          <div className="mt-4 flex flex-wrap gap-3">
                            <button
                              type="button"
                              disabled={isPending}
                              onClick={() =>
                                handleDecision(
                                  transaction.id,
                                  candidate.payment_record_id,
                                  "confirm",
                                )
                              }
                              className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {isPending ? "Saving..." : "Confirm match"}
                            </button>
                            <button
                              type="button"
                              disabled={isPending}
                              onClick={() =>
                                handleDecision(
                                  transaction.id,
                                  candidate.payment_record_id,
                                  "reject",
                                )
                              }
                              className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              Reject match
                            </button>
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    {transaction.warnings.length ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {transaction.warnings.map((warning) => (
                          <Badge key={warning} value={warning} tone="amber" />
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-xl font-semibold text-slate-900">Audit trail</h2>
            <div className="mt-4 space-y-3">
              {auditEvents.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                  No audit events recorded yet.
                </div>
              ) : (
                auditEvents.map((event) => (
                  <div key={event.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{titleize(event.action)}</p>
                        <p className="mt-1 text-sm text-slate-600">
                          {event.reason || event.actor_slack_id || "System event"}
                        </p>
                      </div>
                      <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
                        {formatDateTime(event.created_at)}
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        <div className="space-y-6">
          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-xl font-semibold text-slate-900">Statement provenance</h2>
            {reconciliation.statement ? (
              <div className="mt-4 space-y-3 text-sm text-slate-600">
                <div className="rounded-2xl bg-slate-50 p-4">
                  File: <span className="font-medium text-slate-900">{reconciliation.statement.filename}</span>
                </div>
                <div className="rounded-2xl bg-slate-50 p-4">
                  Extraction: <span className="font-medium text-slate-900">{titleize(reconciliation.statement.extraction_method)}</span>
                </div>
                <div className="rounded-2xl bg-slate-50 p-4">
                  Confidence: <span className="font-medium text-slate-900">{reconciliation.statement.confidence}%</span>
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                No statement provenance is available.
              </div>
            )}
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-xl font-semibold text-slate-900">Completion blockers</h2>
            <div className="mt-4 space-y-3">
              {reconciliation.completion_blockers.length === 0 ? (
                <div className="rounded-2xl bg-emerald-50 p-4 text-sm text-emerald-700">
                  No blockers remain on this reconciliation.
                </div>
              ) : (
                reconciliation.completion_blockers.map((blocker) => (
                  <div key={blocker} className="rounded-2xl bg-amber-50 p-4 text-sm text-amber-800">
                    {blocker}
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-xl font-semibold text-slate-900">Cases</h2>
            <div className="mt-4 space-y-3">
              {cases.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                  No exception cases were created for this run.
                </div>
              ) : (
                cases.map((item) => (
                  <div key={item.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{item.title}</p>
                        <p className="mt-1 text-sm text-slate-600">{item.summary}</p>
                      </div>
                      <Badge value={item.priority} tone="rose" />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge value={titleize(item.state)} tone="amber" />
                      <Badge value={formatMoney(item.value_at_risk)} tone="cyan" />
                    </div>
                    {item.evidence.length ? (
                      <div className="mt-3 rounded-2xl border border-slate-200 bg-white p-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                          Evidence
                        </p>
                        <div className="mt-2 space-y-2">
                          {item.evidence.map((evidence) => (
                            <div key={evidence.id} className="rounded-xl bg-slate-50 p-3 text-sm text-slate-600">
                              <p>{evidence.excerpt}</p>
                              {!evidence.verified ? (
                                <p className="mt-2 text-xs font-semibold uppercase tracking-[0.16em] text-amber-700">
                                  Unverified workspace claim
                                </p>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
