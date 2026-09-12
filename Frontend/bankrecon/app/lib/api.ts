import type { ApiError } from "./types";

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";

  if (!response.ok) {
    const body = contentType.includes("application/json")
      ? ((await response.json()) as ApiError)
      : { code: "HTTP_ERROR", message: await response.text(), details: {} };
    throw new Error(body.message || "Request failed");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  if (!contentType.includes("application/json")) {
    return (await response.text()) as T;
  }

  return (await response.json()) as T;
}

export async function apiFetch<T>(input: RequestInfo | URL, init?: RequestInit) {
  const response = await fetch(input, {
    ...init,
    headers: {
      accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  return parseResponse<T>(response);
}
