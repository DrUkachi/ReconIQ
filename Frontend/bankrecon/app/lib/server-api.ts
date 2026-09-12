import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { auth0 } from "@/lib/auth0";

import { BACKEND_API_BASE_URL, BACKEND_SESSION_COOKIE } from "./config";
import type {
  AuditEventOut,
  CaseDetail,
  CasePage,
  ReconciliationDetail,
  ReconciliationSummary,
  SessionData,
  SettingsOut,
  TransactionDetail,
  TransactionPage,
} from "./types";

async function backendRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const cookieStore = await cookies();
  const backendSession = cookieStore.get(BACKEND_SESSION_COOKIE)?.value;
  const headers = new Headers(init?.headers);

  if (backendSession) {
    headers.set("cookie", `session=${backendSession}`);
  }

  if (!headers.has("accept")) {
    headers.set("accept", "application/json");
  }

  const response = await fetch(`${BACKEND_API_BASE_URL}/api/v1${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Backend request failed with ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function getSession() {
  const cookieStore = await cookies();
  if (!cookieStore.get(BACKEND_SESSION_COOKIE)?.value) {
    const authSession = await auth0.getSession();
    if (authSession?.user?.email) {
      redirect("/auth/complete");
    }
    return null;
  }

  try {
    return await backendRequest<SessionData>("/session");
  } catch {
    const authSession = await auth0.getSession();
    if (authSession?.user?.email) {
      redirect("/auth/complete");
    }
    return null;
  }
}

export async function requireSession() {
  const session = await getSession();
  if (!session) {
    redirect("/login");
  }
  return session;
}

export function getReconciliations() {
  return backendRequest<ReconciliationSummary[]>("/reconciliations");
}

export function getReconciliation(reconciliationId: string) {
  return backendRequest<ReconciliationDetail>(`/reconciliations/${reconciliationId}`);
}

export function getReconciliationTransactions(
  reconciliationId: string,
  searchParams?: URLSearchParams,
) {
  const suffix = searchParams?.toString() ? `?${searchParams.toString()}` : "";
  return backendRequest<TransactionPage>(
    `/reconciliations/${reconciliationId}/transactions${suffix}`,
  );
}

export function getReconciliationAudit(reconciliationId: string) {
  return backendRequest<AuditEventOut[]>(
    `/reconciliations/${reconciliationId}/audit`,
  );
}

export function getTransaction(transactionId: string) {
  return backendRequest<TransactionDetail>(`/transactions/${transactionId}`);
}

export function getCases(searchParams?: URLSearchParams) {
  const suffix = searchParams?.toString() ? `?${searchParams.toString()}` : "";
  return backendRequest<CasePage>(`/cases${suffix}`);
}

export function getCase(caseId: string) {
  return backendRequest<CaseDetail>(`/cases/${caseId}`);
}

export function getSettings() {
  return backendRequest<SettingsOut>("/settings");
}
