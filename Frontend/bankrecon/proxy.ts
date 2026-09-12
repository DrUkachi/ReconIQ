import { NextResponse } from "next/server";
import { auth0, hasAuth0Config } from "./lib/auth0";

export async function proxy(request: Request) {
  if (!hasAuth0Config) {
    const url = new URL("/auth", request.url);
    url.searchParams.set("auth_error", "missing_auth0_config");
    return NextResponse.redirect(url);
  }

  return auth0.middleware(request);
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
  ],
};
