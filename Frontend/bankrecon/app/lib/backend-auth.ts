import "server-only";

// The backend refuses /api/v1 calls without this header. `set` also overwrites any
// value a browser supplied through the proxy.
export function backendHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init);
  headers.set("x-internal-token", process.env.INTERNAL_API_TOKEN ?? "");
  return headers;
}
