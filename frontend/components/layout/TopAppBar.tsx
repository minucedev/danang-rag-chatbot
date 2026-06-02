import Link from "next/link";

export function TopAppBar() {
  return (
    <header className="h-16 shrink-0 bg-surface/80 backdrop-blur-md shadow-sm border-b border-outline-variant/10 z-50">
      <div className="flex items-center justify-between h-full px-6 max-w-screen-xl mx-auto">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <span
            className="material-symbols-outlined text-3xl text-primary"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            explore
          </span>
          <span className="text-lg font-bold text-primary tracking-tight">
            Da Nang AI Concierge
          </span>
        </div>

        {/* Nav tabs — desktop only */}
        <nav className="hidden md:flex items-center gap-6">
          <Link
            href="/chat"
            className="text-primary font-semibold border-b-2 border-primary pb-0.5 text-sm"
          >
            Chat
          </Link>
          <span className="text-on-surface-variant text-sm cursor-not-allowed opacity-50">
            Explore
          </span>
          <span className="text-on-surface-variant text-sm cursor-not-allowed opacity-50">
            Plan
          </span>
        </nav>

        {/* Right actions — desktop only */}
        <div className="hidden md:flex items-center gap-2">
          <button className="p-2 rounded-full hover:bg-surface-container-high transition-colors text-on-surface-variant">
            <span className="material-symbols-outlined text-2xl">notifications</span>
          </button>
          <button className="p-2 rounded-full hover:bg-surface-container-high transition-colors text-on-surface-variant">
            <span className="material-symbols-outlined text-2xl">settings</span>
          </button>
          <div className="w-9 h-9 rounded-full bg-primary-fixed border-2 border-primary-container flex items-center justify-center ml-1">
            <span className="text-xs font-bold text-primary">DN</span>
          </div>
        </div>

        {/* Hamburger — mobile only */}
        <button className="md:hidden p-2 text-on-surface-variant">
          <span className="material-symbols-outlined text-2xl">menu</span>
        </button>
      </div>
    </header>
  );
}
