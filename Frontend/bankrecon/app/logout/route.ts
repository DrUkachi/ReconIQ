import { NextResponse } from "next/server";

import { BACKEND_SESSION_COOKIE } from "@/app/lib/config";

export async function GET(request: Request) {
  const response = NextResponse.redirect(new URL("/auth/logout?returnTo=/login", request.url));
  response.cookies.delete(BACKEND_SESSION_COOKIE);
  return response;
}
