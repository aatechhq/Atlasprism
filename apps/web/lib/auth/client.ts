"use client";

import { createAuthClient } from "@neondatabase/auth/next";

export const authClient = createAuthClient();

/** Read a token out of either response shape.
 *
 * `$fetch` wraps some responses as `{ data, error }` and returns others as the
 * parsed body. The /token endpoint answers `{"token":"..."}` directly
 * (verified against the deployed site), so reading only `.data.token` yields
 * undefined -> null -> no Authorization header -> the API answers
 * "Missing bearer token." Accept both rather than depend on which it is.
 */
function readToken(result: unknown): string | null {
  const r = result as { data?: { token?: string }; token?: string } | null;
  return r?.data?.token ?? r?.token ?? null;
}

async function fetchToken(): Promise<string | null> {
  const token = readToken(await authClient.$fetch<{ token: string }>("/token"));
  if (token) return token;
  // The browser's `local.session_data` cookie lives only 300s. Once it lapses
  // the token call comes back empty, so refresh the session and ask again
  // before giving up and sending an unauthenticated request.
  const session = await authClient.getSession();
  if (!session?.data) return null;
  return readToken(await authClient.$fetch<{ token: string }>("/token"));
}

/** Expiry of a JWT, in ms. Falls back to a short window if it cannot be read. */
function expiryOf(token: string, fallbackMs: number): number {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const exp = JSON.parse(atob(payload))?.exp;
    if (typeof exp === "number") return exp * 1000;
  } catch {
    /* not decodable: use the fallback */
  }
  return fallbackMs;
}

let cached: { token: string; expiresAt: number } | null = null;
let inFlight: Promise<string | null> | null = null;

/** The bearer token for API calls, or null when not signed in.
 *
 * Concurrent callers share ONE request. A dashboard screen fires several
 * `api()` calls on mount and each one asks for a token; without this, those
 * become parallel /token requests that race, and the losers resolve to null —
 * which is why some panels rendered while others showed "Missing bearer
 * token." The token is then reused until shortly before it expires.
 */
export async function getAccessToken(): Promise<string | null> {
  const now = Date.now();
  if (cached && cached.expiresAt > now + 30_000) return cached.token;
  if (inFlight) return inFlight;

  inFlight = (async () => {
    try {
      const token = await fetchToken();
      cached = token
        ? { token, expiresAt: expiryOf(token, now + 60_000) }
        : null;
      return token;
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}
