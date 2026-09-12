"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  auditTrail,
  exceptionQueue,
  reconciliationRows,
  slackSettings,
  transactionMatches,
} from "@/app/lib/mock-data";

const tabs = ["Overview", "Transactions", "Exceptions", "Audit"] as const;

type TabKey = (typeof tabs)[number];

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

function StatusPill({ status }: { status: string }) {
  const styles: Record<string, string> = {
    matched: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    in_review: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
    exception: "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
    pending: "bg-slate-100 text-slate-700 ring-1 ring-slate-200",
  };

  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${styles[status] ?? styles.pending}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function RiskPill({ risk }: { risk: string }) {
  const styles: Record<string, string> = {
    Low: "bg-emerald-50 text-emerald-700",
    Medium: "bg-amber-50 text-amber-700",
    High: "bg-rose-50 text-rose-700",
  };

  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${styles[risk] ?? styles.Medium}`}>{risk}</span>;
}

export function ReconciliationDashboard() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("Overview");
  const [searchTerm, setSearchTerm] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [uploadLabel, setUploadLabel] = useState("No file uploaded yet");
  const [rows, setRows] = useState(reconciliationRows);
  const [exceptions, setExceptions] = useState(exceptionQueue);
  const [reason, setReason] = useState("Customer dispute note required");
  const [notes, setNotes] = useState<Record<string, string>>({});

  const filteredTransactions = transactionMatches.filter((tx) => {
    const value = searchTerm.trim().toLowerCase();
    if (!value) return true;
    return (
      tx.reference.toLowerCase().includes(value) ||
      tx.customer.toLowerCase().includes(value) ||
      tx.status.toLowerCase().includes(value)
    );
  });

  const handleExportReport = () => {
    const csvRows = [
      ["id", "customer", "status", "amount", "updatedAt"],
      ...rows.map((row) => [row.id, row.customer, row.status, row.totalValue.toString(), row.updatedAt]),
    ];
    const csv = csvRows.map((line) => line.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = "rekoniq-report.csv";
    link.click();
    URL.revokeObjectURL(url);
    setToast("Report exported successfully.");
  };

  const handleAddNote = (id: string) => {
    const note = window.prompt(`Add note for ${id}`);
    if (!note || !note.trim()) return;
    setNotes((prev) => ({ ...prev, [id]: note.trim() }));
    setToast(`Note added to ${id}.`);
  };

  const handleEscalate = (id: string) => {
    setExceptions((prev) =>
      prev.map((item) => (item.id === id ? { ...item, escalation: "Escalated" } : item)),
    );
    setToast(`${id} escalated successfully.`);
  };

  const handleResolve = (id: string) => {
    setExceptions((prev) =>
      prev.map((item) => (item.id === id ? { ...item, escalation: "Resolved", requiredReason: reason } : item)),
    );
    setToast(`${id} marked as resolved.`);
  };

  const handleValidateFiles = () => {
    setToast("Uploaded files validated successfully.");
    setUploadLabel("Validated and ready");
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadLabel(`${file.name} selected`);
    setToast(`${file.name} is ready for validation.`);
  };

  return (
    <main className="space-y-6 p-4 md:p-6">
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={handleFileChange}
      />

      {toast ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {toast}
        </div>
      ) : null}

      <header className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">Reconciliations</p>
          <h1 className="mt-2 text-3xl font-bold text-slate-900">Home</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleExportReport}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Export report
          </button>
          <button
            type="button"
            onClick={() => router.push("/reconciliations/new")}
            className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800"
          >
            New reconciliation
          </button>
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Open reconciliations", value: "128", change: "+12% vs last week", tone: "cyan" },
          { label: "Auto-match rate", value: "94.6%", change: "+2.3 pts", tone: "emerald" },
          { label: "Exception queue", value: "24", change: "6 escalated", tone: "amber" },
          { label: "Avg. review SLA", value: "3.8h", change: "-0.7h", tone: "violet" },
        ].map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => setActiveTab(item.label.includes("Exception") ? "Exceptions" : item.label.includes("Auto") ? "Transactions" : "Overview")}
            className="rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-cyan-200 hover:shadow-md"
          >
            <p className="text-sm text-slate-500">{item.label}</p>
            <div className="mt-3 flex items-end justify-between gap-3">
              <span className="text-3xl font-bold text-slate-900">{item.value}</span>
              <span className={`rounded-full px-2 py-1 text-xs font-medium ${
                item.tone === "cyan" ? "bg-cyan-50 text-cyan-700" :
                item.tone === "emerald" ? "bg-emerald-50 text-emerald-700" :
                item.tone === "amber" ? "bg-amber-50 text-amber-700" : "bg-violet-50 text-violet-700"
              }`}>
                {item.change}
              </span>
            </div>
          </button>
        ))}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.65fr_1fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900">Status overview</h2>
            <button type="button" onClick={() => setActiveTab("Transactions")} className="text-sm font-medium text-cyan-700">
              View all
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-3 pr-4 font-medium">Reconciliation</th>
                  <th className="pb-3 pr-4 font-medium">Customer</th>
                  <th className="pb-3 pr-4 font-medium">Amount</th>
                  <th className="pb-3 pr-4 font-medium">Status</th>
                  <th className="pb-3 pr-4 font-medium">Risk</th>
                  <th className="pb-3 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-slate-100">
                    <td className="py-3 pr-4">
                      <div>
                        <div className="font-semibold text-slate-900">{row.id}</div>
                        <div className="text-xs text-slate-500">{row.period}</div>
                      </div>
                    </td>
                    <td className="py-3 pr-4">{row.customer}</td>
                    <td className="py-3 pr-4">{currencyFormatter.format(row.totalValue)}</td>
                    <td className="py-3 pr-4"><StatusPill status={row.status} /></td>
                    <td className="py-3 pr-4"><RiskPill risk={row.risk} /></td>
                    <td className="py-3">{row.updatedAt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">Uploads</h2>
            <div className="mt-4 space-y-3">
              <div className="rounded-xl border border-dashed border-cyan-200 bg-cyan-50 p-4">
                <p className="text-sm font-semibold text-cyan-800">Statement PDF</p>
                <p className="mt-1 text-xs text-cyan-700">06_statement_jun.pdf • 4.2 MB</p>
              </div>
              <div className="rounded-xl border border-dashed border-violet-200 bg-violet-50 p-4">
                <p className="text-sm font-semibold text-violet-800">Payment CSV</p>
                <p className="mt-1 text-xs text-violet-700">payments_jun_2026.csv • 1.9 MB</p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                Upload new
              </button>
              <button
                type="button"
                onClick={handleValidateFiles}
                className="rounded-xl bg-cyan-600 px-3 py-2 text-sm font-semibold text-white hover:bg-cyan-500"
              >
                Validate files
              </button>
            </div>
            <p className="mt-3 text-xs text-slate-500">{uploadLabel}</p>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">Slack connection</h2>
            <div className="mt-4 space-y-3">
              {slackSettings.map((setting) => (
                <div key={setting.channel} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-slate-800">{setting.channel}</span>
                    <button
                      type="button"
                      onClick={() => setToast(`${setting.channel} ${setting.enabled ? "disconnected" : "connected"}.`)}
                      className={`rounded-full px-2 py-1 text-[10px] font-medium ${
                        setting.enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-200 text-slate-600"
                      }`}
                    >
                      {setting.enabled ? "Connected" : "Disconnected"}
                    </button>
                  </div>
                  <ul className="mt-2 space-y-1 text-xs text-slate-600">
                    {setting.alerts.map((alert) => (
                      <li key={alert}>• {alert}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.65fr_1fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <h2 className="text-lg font-semibold text-slate-900">Reconciliation workspace</h2>
            <div className="flex flex-wrap gap-2">
              {tabs.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                  className={`rounded-xl px-3 py-2 text-sm font-medium transition ${
                    activeTab === tab
                      ? "bg-slate-900 text-white"
                      : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-5">
            {activeTab === "Overview" && (
              <div className="space-y-5">
                <div className="grid gap-4 md:grid-cols-2">
                  {[
                    { label: "Statement variant match", value: "96.2%" },
                    { label: "Payment coverage", value: "89.4%" },
                  ].map((metric) => (
                    <div key={metric.label} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <p className="text-sm text-slate-500">{metric.label}</p>
                      <p className="mt-2 text-2xl font-bold text-slate-900">{metric.value}</p>
                    </div>
                  ))}
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="font-semibold text-slate-900">Evidence-based match detail</h3>
                    <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">97% confidence</span>
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    {[
                      "Invoice reference matches",
                      "Settlement date overlaps by 1 day",
                      "Customer account suffix verified",
                    ].map((item) => (
                      <div key={item} className="rounded-lg bg-white p-3 text-sm text-slate-600 ring-1 ring-slate-200">
                        {item}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {activeTab === "Transactions" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Search transaction or customer"
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 outline-none focus:border-cyan-500 focus:bg-white"
                  />
                  <button
                    type="button"
                    onClick={() => setToast(`Showing ${filteredTransactions.length} matching transactions.`)}
                    className="rounded-xl bg-slate-900 px-3 py-2.5 text-sm font-medium text-white"
                  >
                    Filter
                  </button>
                </div>

                <div className="overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="text-slate-500">
                      <tr>
                        <th className="pb-3 pr-4 font-medium">Reference</th>
                        <th className="pb-3 pr-4 font-medium">Customer</th>
                        <th className="pb-3 pr-4 font-medium">Date</th>
                        <th className="pb-3 pr-4 font-medium">Amount</th>
                        <th className="pb-3 pr-4 font-medium">Score</th>
                        <th className="pb-3 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTransactions.map((tx) => (
                        <tr key={tx.id} className="border-t border-slate-100">
                          <td className="py-3 pr-4 font-medium text-slate-800">{tx.reference}</td>
                          <td className="py-3 pr-4">{tx.customer}</td>
                          <td className="py-3 pr-4">{tx.date}</td>
                          <td className="py-3 pr-4">{currencyFormatter.format(tx.amount)}</td>
                          <td className="py-3 pr-4">{tx.matchScore}%</td>
                          <td className="py-3">
                            <span className={`rounded-full px-2 py-1 text-xs font-medium ${
                              tx.status === "Auto-match" ? "bg-emerald-50 text-emerald-700" :
                              tx.status === "Manual review" ? "bg-amber-50 text-amber-700" : "bg-rose-50 text-rose-700"
                            }`}>
                              {tx.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {activeTab === "Exceptions" && (
              <div className="space-y-4">
                {exceptions.map((item) => (
                  <div key={item.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-900">{item.id}</span>
                          <span className={`rounded-full px-2 py-1 text-xs font-medium ${
                            item.priority === "High" ? "bg-rose-50 text-rose-700" :
                            item.priority === "Medium" ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"
                          }`}>
                            {item.priority}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-slate-600">{item.customer} • {item.reason}</p>
                      </div>
                      <span className="rounded-full border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-600">
                        {item.escalation}
                      </span>
                    </div>
                    <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <p className="text-sm text-slate-600">{currencyFormatter.format(item.amount)} • {item.requiredReason}</p>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => handleAddNote(item.id)}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                        >
                          Add note
                        </button>
                        <button
                          type="button"
                          onClick={() => handleEscalate(item.id)}
                          className="rounded-xl bg-amber-500 px-3 py-2 text-sm font-semibold text-white hover:bg-amber-400"
                        >
                          Escalate
                        </button>
                        {notes[item.id] ? (
                          <span className="rounded-xl bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700">
                            {notes[item.id]}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeTab === "Audit" && (
              <div className="space-y-4">
                {auditTrail.map((event) => (
                  <div key={event.id} className="flex gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white">
                      {event.actor.slice(0, 1)}
                    </div>
                    <div className="flex-1">
                      <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                        <div className="font-medium text-slate-900">{event.actor} • {event.action}</div>
                        <span className="text-xs text-slate-500">{event.time}</span>
                      </div>
                      <p className="mt-1 text-sm text-slate-600">{event.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <aside className="space-y-6">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">Exception queue</h2>
            <div className="mt-4 space-y-3">
              {exceptions.slice(0, 3).map((item) => (
                <div key={item.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-slate-800">{item.id}</span>
                    <span className={`rounded-full px-2 py-1 text-[10px] font-medium ${
                      item.priority === "High" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"
                    }`}>{item.priority}</span>
                  </div>
                  <p className="mt-2 text-sm text-slate-600">{item.customer}</p>
                  <p className="text-sm text-slate-500">{currencyFormatter.format(item.amount)}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">Required resolution</h2>
            <div className="mt-4 space-y-3">
              <label className="block text-sm font-medium text-slate-700">Reason category</label>
              <select
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 outline-none focus:border-cyan-500 focus:bg-white"
              >
                <option>Customer dispute note required</option>
                <option>Finance approval required</option>
                <option>Duplicate receipt investigation</option>
              </select>
              <button
                type="button"
                onClick={() => handleResolve(exceptions[0]?.id ?? "EX-445")}
                className="w-full rounded-xl bg-cyan-600 px-3 py-2.5 text-sm font-semibold text-white hover:bg-cyan-500"
              >
                Resolve exception
              </button>
            </div>
          </div>
        </aside>
      </section>
    </main>
  );
}
