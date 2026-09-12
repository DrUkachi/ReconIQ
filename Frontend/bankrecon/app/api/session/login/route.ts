import { NextResponse } from "next/server";

import { BACKEND_API_BASE_URL, BACKEND_SESSION_COOKIE } from "@/app/lib/config";

function extractSessionCookie(header: string | null) {
  if (!header) return null;
  const match = header.match(/session=([^;]+)/);
  return match?.[1] ?? null;
}

export async function POST(request: Request) {
  const response = await fetch(`${BACKEND_API_BASE_URL}/api/v1/session/login`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body: await request.text(),
    redirect: "manual",
    cache: "no-store",
  });

  const body = await response.text();
  const headers = new Headers({
    "content-type": response.headers.get("content-type") ?? "application/json",
  });
  const correlationId = response.headers.get("x-correlation-id");
  if (correlationId) {
    headers.set("x-correlation-id", correlationId);
  }
  const nextResponse = new NextResponse(body, {
    status: response.status,
    headers,
  });

  if (response.ok) {
    const backendSession = extractSessionCookie(response.headers.get("set-cookie"));
    if (backendSession) {
      nextResponse.cookies.set(BACKEND_SESSION_COOKIE, backendSession, {
        httpOnly: true,
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
        path: "/",
      });
    }
  }

  return nextResponse;
}
