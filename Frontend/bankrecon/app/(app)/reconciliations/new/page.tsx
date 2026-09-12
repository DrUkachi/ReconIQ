"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/app/lib/api";
import type { ReconciliationSummary } from "@/app/lib/types";

export default function NewReconciliationPage() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    account_last4: "DEMO",
    period_start: "2026-08-01",
    period_end: "2026-08-31",
  });

  const handleChange = (key: keyof typeof form, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    const formData = new FormData(event.currentTarget);
    formData.set("account_last4", form.account_last4);
    formData.set("period_start", form.period_start);
    formData.set("period_end", form.period_end);

    try {
      const response = await apiFetch<ReconciliationSummary[]>(
        "/api/backend/reconciliations/import",
        {
          method: "POST",
          headers: {
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: formData,
        },
      );
      const target = response[0]?.id;
      router.push(target ? `/reconciliations/${target}` : "/reconciliations");
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Unable to create reconciliation.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="mx-auto max-w-4xl space-y-6">
      <header className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">
          New workflow
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-900">Create reconciliation</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
          Upload the signed bank statement PDF and the matching ledger CSV. The backend will parse,
          persist, and run matching immediately.
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div className="grid gap-6 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Account last 4
            <input
              value={form.account_last4}
              onChange={(event) => handleChange("account_last4", event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
            />
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Period start
            <input
              type="date"
              value={form.period_start}
              onChange={(event) => handleChange("period_start", event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
            />
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Period end
            <input
              type="date"
              value={form.period_end}
              onChange={(event) => handleChange("period_end", event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
            />
          </label>

          <div className="rounded-2xl border border-cyan-100 bg-cyan-50 p-4 text-sm text-slate-600">
            Use the signed export profile the backend already supports. The bank file must be a
            readable PDF table export, and the ledger file must keep the five expected CSV columns.
          </div>

          <label className="block text-sm font-medium text-slate-700 md:col-span-2">
            Bank statement PDF
            <input
              required
              name="bank_file"
              type="file"
              accept=".pdf,application/pdf"
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-900 file:mr-4 file:rounded-lg file:border-0 file:bg-slate-900 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white"
            />
          </label>

          <label className="block text-sm font-medium text-slate-700 md:col-span-2">
            Ledger CSV
            <input
              required
              name="ledger_file"
              type="file"
              accept=".csv,text/csv"
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-900 file:mr-4 file:rounded-lg file:border-0 file:bg-cyan-700 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white"
            />
          </label>
        </div>

        {error ? (
          <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? "Creating..." : "Create reconciliation"}
          </button>
          <button
            type="button"
            onClick={() => router.push("/reconciliations")}
            className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Back to dashboard
          </button>
        </div>
      </form>
    </main>
  );
}
