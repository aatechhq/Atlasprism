import type { Metadata } from "next";
import "@neondatabase/auth/ui/css";
import "./globals.css";
import { AuthProvider } from "@/components/auth-provider";

export const metadata: Metadata = { title: "ATLAS Prism", description: "Evaluation evidence for N-ATLAS integrations" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en" suppressHydrationWarning><body><AuthProvider>{children}</AuthProvider></body></html>; }
