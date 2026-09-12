import { NextResponse } from "next/server";

import { BACKEND_API_BASE_URL, BACKEND_SESSION_COOKIE } from "@/app/lib/config";
import { auth0 } from "@/lib/auth0";

function extractSessionCookie(header: string | null) {
  if (!header) return null;
  const match = header.match(/session=([^;]+)/);
  return match?.[1] ?? null;
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const returnTo = url.searchParams.get("returnTo") || "/reconciliations";
  const authSession = await auth0.getSession();

  if (!authSession?.user?.email) {
    return NextResponse.redirect(new URL(`/auth/login?returnTo=${encodeURIComponent("/auth/complete")}`, url));
  }

  const response = await fetch(`${BACKEND_API_BASE_URL}/api/v1/session/login`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify({
      email: authSession.user.email,
      name: authSession.user.name ?? authSession.user.nickname ?? authSession.user.email,
    }),
    cache: "no-store",
    redirect: "manual",
  });

  if (!response.ok) {
    const body = await response.text();
    return new NextResponse(body || "Unable to create backend session.", {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "text/plain; charset=utf-8",
      },
    });
  }

  const nextResponse = NextResponse.redirect(new URL(returnTo, url));
  const backendSession = extractSessionCookie(response.headers.get("set-cookie"));

  if (!backendSession) {
    return new NextResponse("Missing backend session cookie.", { status: 502 });
  }

  nextResponse.cookies.set(BACKEND_SESSION_COOKIE, backendSession, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });

  return nextResponse;
}
