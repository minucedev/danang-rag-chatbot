import { TopAppBar } from "@/components/layout/TopAppBar";
import { MobileBottomNav } from "@/components/layout/MobileBottomNav";
import { SessionSidebar } from "@/components/sessions/SessionSidebar";

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col h-full">
      <TopAppBar />
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <SessionSidebar />
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {children}
        </main>
      </div>
      <MobileBottomNav />
    </div>
  );
}
