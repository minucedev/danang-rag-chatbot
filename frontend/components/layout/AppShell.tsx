import { TopAppBar } from "@/components/layout/TopAppBar";
import { MobileBottomNav } from "@/components/layout/MobileBottomNav";

// Khung chung cho các trang ngoài chat (/profile, /recommend, /saved, /itineraries):
// cùng TopAppBar + MobileBottomNav, KHÔNG có SessionSidebar.
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col h-full">
      <TopAppBar />
      <main className="flex-1 min-h-0 overflow-y-auto">{children}</main>
      <MobileBottomNav />
    </div>
  );
}
