"use client";

import { AuthUIProvider } from "@neondatabase/auth/react/ui";
import { authClient } from "@/lib/auth/client";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  return (
    <AuthUIProvider
      authClient={authClient}
      redirectTo="/dashboard"
      social={{ providers: ["google"] }}
    >
      {children}
    </AuthUIProvider>
  );
}
