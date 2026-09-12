import { NextResponse } from "next/server";

import { BACKEND_SESSION_COOKIE } from "@/app/lib/config";

export async function GET(request: Request) {
  // Auth0 needs an absolute returnTo that exactly matches an Allowed Logout URL, and the
  // bare origin (no path, no trailing slash) is the entry registered per environment.
  const returnTo = process.env.APP_BASE_URL ?? new URL(request.url).origin;
  const response = NextResponse.redirect(
    new URL(`/auth/logout?returnTo=${encodeURIComponent(returnTo)}`, request.url),
  );
  response.cookies.delete(BACKEND_SESSION_COOKIE);
  return response;
}
