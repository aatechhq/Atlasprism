const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const READ_TIMEOUT_MS = 15_000;
const VERIFY_TIMEOUT_MS = 130_000;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
    const field = Array.isArray(first?.loc) ? first.loc.at(-1) : undefined;
    return field ? `${String(field)}: ${first?.msg ?? "invalid"}` : (first?.msg ?? `Request failed (${status})`);
  }
  const message = (detail as { message?: string } | null)?.message;
  return message ?? `Request failed (${status})`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();
  const controller = new AbortController();
  const timeoutMs = /^\/connections\/[^/]+\/verify$/.test(path)
    ? VERIFY_TIMEOUT_MS
    : READ_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(response.status, errorMessage(body, response.status));
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if ((error as Error).name === "AbortError") throw new ApiError(408, "The API did not respond in time.");
    throw new ApiError(0, "The Prism API is unavailable. Check the API URL and service status.");
  } finally { clearTimeout(timer); }
}

export async function download(path: string, filename: string) {
  const token = await getAccessToken();
  const response = await fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) throw new ApiError(response.status, "Export could not be generated.");
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url);
}
import { getAccessToken } from "@/lib/auth/client";
