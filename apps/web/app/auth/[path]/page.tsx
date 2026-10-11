import { notFound } from "next/navigation";
import { AuthPage } from "@/components/auth-page";

const paths = new Set([
  "callback", "email-otp", "email-verification", "forgot-password",
  "magic-link", "recover-account", "reset-password", "sign-in",
  "sign-out", "sign-up", "two-factor", "accept-invitation",
]);

export default async function NeonAuthPage({ params }: { params: Promise<{ path: string }> }) {
  const { path } = await params;
  if (!paths.has(path)) notFound();
  return <AuthPage mode={path as Parameters<typeof AuthPage>[0]["mode"]} />;
}
