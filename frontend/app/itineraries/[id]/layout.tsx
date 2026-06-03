// Layout tối giản (không nav) để in ra PDF sạch.
export default function ItineraryDetailLayout({ children }: { children: React.ReactNode }) {
  return <div className="h-full overflow-y-auto bg-surface">{children}</div>;
}
