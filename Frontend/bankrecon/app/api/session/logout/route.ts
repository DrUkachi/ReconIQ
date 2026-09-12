import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { BACKEND_API_BASE_URL, BACKEND_SESSION_COOKIE } from "@/app/lib/config";

export async function POST() {
  const cookieStore = await cookies();
  const backendSession = cookieStore.get(BACKEND_SESSION_COOKIE)?.value;

  if (backendSession) {
    await fetch(`${BACKEND_API_BASE_URL}/api/v1/session/logout`, {
      method: "POST",
      headers: {
        cookie: `session=${backendSession}`,
        accept: "application/json",
      },
      cache: "no-store",
    }).catch(() => undefined);
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.delete(BACKEND_SESSION_COOKIE);
  return response;
}
