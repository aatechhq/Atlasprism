import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "ATLAS Prism", description: "Evaluation evidence for N-ATLAS integrations" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
