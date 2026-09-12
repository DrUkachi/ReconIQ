export const BACKEND_SESSION_COOKIE = "rekoniq_backend_session";

export const BACKEND_API_BASE_URL =
  process.env.BACKEND_API_BASE_URL ??
  process.env.NEXT_PUBLIC_BACKEND_API_BASE_URL ??
  "http://127.0.0.1:8000";
