// Versioned: bump the suffix when the backend identity mapping changes, so every browser
// re-runs /auth/complete once instead of keeping a session for the old identity.
export const BACKEND_SESSION_COOKIE = "rekoniq_backend_session_v2";
export const LEGACY_BACKEND_SESSION_COOKIES = ["rekoniq_backend_session"];

export const BACKEND_API_BASE_URL =
  process.env.BACKEND_API_BASE_URL ??
  process.env.NEXT_PUBLIC_BACKEND_API_BASE_URL ??
  "http://127.0.0.1:8000";
