import { AppShell } from "@/components/layout/AppShell";

export default function RecommendLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
