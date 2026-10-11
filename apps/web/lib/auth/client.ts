"use client";

import { createAuthClient } from "@neondatabase/auth/next";

export const authClient = createAuthClient();

export async function getAccessToken(): Promise<string | null> {
  const result = await authClient.$fetch<{ token: string }>("/token");
  return result.data?.token ?? null;
}
