"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function NewReconciliationPage() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [form, setForm] = useState({
    customer: "Northwind Labs",
    period: "Jun 2026",
    fileType: "Statement PDF",
    notes: "Match high-value vendor payments and verify account suffixes.",
  });

  const handleChange = (key: keyof typeof form, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);

    setTimeout(() => {
      setIsSubmitting(false);
      router.push("/reconciliations");
    }, 600);
  };

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-4 md:p-6">
      <header className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">New workflow</p>
          <h1 className="mt-2 text-3xl font-bold text-slate-900">Create reconciliation</h1>
        </div>
        <button
          type="button"
          onClick={() => router.push("/reconciliations")}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Back to dashboard
        </button>
      </header>

      <form onSubmit={handleSubmit} className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="grid gap-6 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Customer
            <input
              value={form.customer}
              onChange={(event) => handleChange("customer", event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
            />
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Reconciliation period
            <input
              value={form.period}
              onChange={(event) => handleChange("period", event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
            />
          </label>

          <label className="block text-sm font-medium text-slate-700 md:col-span-2">
            File type
            <select
              value={form.fileType}
              onChange={(event) => handleChange("fileType", event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
            >
              <option>Statement PDF</option>
              <option>Payment CSV</option>
              <option>Bank feed export</option>
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700 md:col-span-2">
            Notes
            <textarea
              value={form.notes}
              onChange={(event) => handleChange("notes", event.target.value)}
              rows={4}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
            />
          </label>
        </div>

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
            onClick={() => setForm({
              customer: "Northwind Labs",
              period: "Jun 2026",
              fileType: "Statement PDF",
              notes: "Match high-value vendor payments and verify account suffixes.",
            })}
            className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Reset
          </button>
        </div>
      </form>
    </main>
  );
}
