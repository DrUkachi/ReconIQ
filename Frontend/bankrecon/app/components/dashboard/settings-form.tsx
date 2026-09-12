"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/app/lib/api";
import { formatMoney } from "@/app/lib/format";
import type { SettingsOut } from "@/app/lib/types";

export function SettingsForm({ settings }: { settings: SettingsOut }) {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    approval_value_threshold_minor: settings.approval_value_threshold.minor.toString(),
    recon_channel_id: settings.recon_channel_id ?? "",
  });

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      await apiFetch<SettingsOut>("/api/backend/settings", {
        method: "PUT",
        headers: {
          "content-type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          approval_value_threshold_minor: Number(form.approval_value_threshold_minor),
          recon_channel_id: form.recon_channel_id || null,
        }),
      });
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to save settings.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">
          Workspace settings
        </p>
        <h1 className="mt-2 text-3xl font-bold text-slate-900">Approval and routing</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
          Current threshold is {formatMoney(settings.approval_value_threshold)}. Update the values
          below to tune what the backend review flow requires from the team.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <label className="block text-sm font-medium text-slate-700">
          Approval threshold minor units
          <input
            value={form.approval_value_threshold_minor}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                approval_value_threshold_minor: event.target.value,
              }))
            }
            className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
          />
        </label>

        <label className="block text-sm font-medium text-slate-700">
          Slack reconciliation channel ID
          <input
            value={form.recon_channel_id}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                recon_channel_id: event.target.value,
              }))
            }
            placeholder="C0123456789"
            className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none focus:border-cyan-500 focus:bg-white"
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
          {isSubmitting ? "Saving..." : "Save settings"}
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
  );
}
