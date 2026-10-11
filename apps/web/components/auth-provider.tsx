"use client";

import { AuthUIProvider } from "@neondatabase/auth/react/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { authClient } from "@/lib/auth/client";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  return (
    <AuthUIProvider
      authClient={authClient}
      emailOTP
      emailVerification={{ otp: true }}
      Link={Link}
      navigate={router.push}
      replace={router.replace}
      onSessionChange={() => router.refresh()}
      redirectTo="/dashboard"
      social={{ providers: ["google"] }}
    >
      {children}
    </AuthUIProvider>
  );
}
