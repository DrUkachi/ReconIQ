import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { backendHeaders } from "@/app/lib/backend-auth";
import { BACKEND_API_BASE_URL, BACKEND_SESSION_COOKIE } from "@/app/lib/config";

export async function GET() {
  const cookieStore = await cookies();
  const backendSession = cookieStore.get(BACKEND_SESSION_COOKIE)?.value;

  if (!backendSession) {
    return NextResponse.json(
      { code: "E_AUTHZ", message: "Only signed-in users can approve this.", details: {} },
      { status: 403 },
    );
  }

  const response = await fetch(`${BACKEND_API_BASE_URL}/api/v1/session`, {
    headers: backendHeaders({
      accept: "application/json",
      cookie: `session=${backendSession}`,
    }),
    cache: "no-store",
  });

  return new NextResponse(await response.text(), {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}
