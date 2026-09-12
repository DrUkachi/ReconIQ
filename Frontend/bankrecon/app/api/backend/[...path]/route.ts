import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { backendHeaders } from "@/app/lib/backend-auth";
import { BACKEND_API_BASE_URL, BACKEND_SESSION_COOKIE } from "@/app/lib/config";

const responseHeaders = [
  "content-type",
  "content-disposition",
  "x-correlation-id",
];

async function proxyRequest(
  request: Request,
  context: {
    params?: Promise<{ path?: string[] }> | { path?: string[] };
  },
) {
  const resolvedParams =
    context.params instanceof Promise ? await context.params : context.params;
  const path = (resolvedParams?.path ?? []).join("/");
  const incoming = new URL(request.url);
  const target = new URL(`${BACKEND_API_BASE_URL}/api/v1/${path}`);
  target.search = incoming.search;

  const cookieStore = await cookies();
  const backendSession = cookieStore.get(BACKEND_SESSION_COOKIE)?.value;
  const headers = backendHeaders(request.headers);

  headers.delete("host");
  headers.delete("cookie");
  headers.delete("content-length");

  if (backendSession) {
    headers.set("cookie", `session=${backendSession}`);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const backendResponse = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    redirect: "manual",
    cache: "no-store",
  });

  const body = await backendResponse.arrayBuffer();
  const outgoingHeaders = new Headers();
  for (const header of responseHeaders) {
    const value = backendResponse.headers.get(header);
    if (value) {
      outgoingHeaders.set(header, value);
    }
  }

  return new NextResponse(body, {
    status: backendResponse.status,
    headers: outgoingHeaders,
  });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
