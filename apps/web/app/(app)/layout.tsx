import { ProtectedLayout } from "@/components/workspace";
export default function Layout({ children }: { children: React.ReactNode }) { return <ProtectedLayout>{children}</ProtectedLayout>; }
