"use client";
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  useProfileSession,
  useProfileQuery,
  useUpsertProfile,
  useDeleteProfile,
  type UserProfile,
} from "@/hooks/useProfile";
import {
  INTERESTS,
  COMPANIONS,
  BUDGET_LEVELS,
  LANGUAGES,
  type Interest,
  type Companions,
  type BudgetLevel,
  type Language,
} from "@/constants/profileOptions";

export default function ProfilePage() {
  const sessionId = useProfileSession();
  const { data: profile, isLoading } = useProfileQuery(sessionId);
  const upsert = useUpsertProfile();
  const del = useDeleteProfile();

  const [displayName, setDisplayName] = useState("");
  const [tripStart, setTripStart] = useState("");
  const [tripEnd, setTripEnd] = useState("");
  const [companions, setCompanions] = useState<Companions | "">("");
  const [budgetLevel, setBudgetLevel] = useState<BudgetLevel | "">("");
  const [interests, setInterests] = useState<Interest[]>([]);
  const [dietary, setDietary] = useState("");
  const [language, setLanguage] = useState<Language>("vi");
  const [seeded, setSeeded] = useState(false);

  // Seed form 1 lần khi hồ sơ tải về (render-time, có cờ chống ghi đè chỉnh sửa của user).
  if (profile && !seeded) {
    setSeeded(true);
    setDisplayName(profile.displayName ?? "");
    setTripStart(profile.tripDates?.start ?? "");
    setTripEnd(profile.tripDates?.end ?? "");
    setCompanions(profile.companions ?? "");
    setBudgetLevel(profile.budgetLevel ?? "");
    setInterests(profile.interests ?? []);
    setDietary(profile.dietary ?? "");
    setLanguage(profile.language ?? "vi");
  }

  function toggleInterest(value: Interest) {
    setInterests((prev) =>
      prev.includes(value) ? prev.filter((i) => i !== value) : [...prev, value],
    );
  }

  async function handleSave() {
    if (!sessionId) return;
    if ((tripStart && !tripEnd) || (!tripStart && tripEnd)) {
      toast.error("Vui lòng chọn cả ngày bắt đầu và kết thúc.");
      return;
    }
    if (tripStart && tripEnd && tripEnd < tripStart) {
      toast.error("Ngày kết thúc phải sau ngày bắt đầu.");
      return;
    }
    const payload: UserProfile = {
      displayName: displayName.trim() || null,
      tripDates: tripStart && tripEnd ? { start: tripStart, end: tripEnd } : null,
      durationDays: null,
      companions: companions || null,
      budgetLevel: budgetLevel || null,
      interests,
      dietary: dietary.trim() || null,
      language,
    };
    try {
      await upsert.mutateAsync({ sessionId, profile: payload });
      toast.success("Đã lưu hồ sơ.");
    } catch {
      toast.error("Lưu hồ sơ thất bại.");
    }
  }

  async function handleClear() {
    if (!sessionId) return;
    try {
      await del.mutateAsync(sessionId);
      setDisplayName(""); setTripStart(""); setTripEnd("");
      setCompanions(""); setBudgetLevel(""); setInterests([]);
      setDietary(""); setLanguage("vi");
      toast.success("Đã xoá hồ sơ.");
    } catch {
      toast.error("Xoá hồ sơ thất bại.");
    }
  }

  const inputCls =
    "w-full rounded-lg border border-outline-variant/40 bg-surface-container-lowest px-3 py-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/40";

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-on-surface">Hồ sơ du lịch</h1>
        <p className="text-sm text-on-surface-variant mt-1">
          Điền sở thích để nhận gợi ý cá nhân hoá ở mục{" "}
          <Link href="/recommend" className="text-primary underline">Gợi ý</Link>.
        </p>
      </div>

      {isLoading && !profile ? (
        <p className="text-sm text-on-surface-variant">Đang tải…</p>
      ) : (
        <div className="space-y-5">
          {/* Tên hiển thị */}
          <div>
            <label className="block text-sm font-medium text-on-surface mb-1.5">Tên hiển thị</label>
            <input
              className={inputCls}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Vd: Minh"
              maxLength={80}
            />
          </div>

          {/* Ngày đi */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-on-surface mb-1.5">Ngày bắt đầu</label>
              <input type="date" className={inputCls} value={tripStart} onChange={(e) => setTripStart(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-on-surface mb-1.5">Ngày kết thúc</label>
              <input type="date" className={inputCls} value={tripEnd} onChange={(e) => setTripEnd(e.target.value)} />
            </div>
          </div>

          {/* Đi cùng */}
          <div>
            <label className="block text-sm font-medium text-on-surface mb-1.5">Đi cùng</label>
            <div className="flex flex-wrap gap-2">
              {COMPANIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setCompanions((c) => (c === opt.value ? "" : opt.value))}
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm border transition-colors ${
                    companions === opt.value
                      ? "bg-primary-container text-on-primary-container border-primary"
                      : "border-outline-variant/40 text-on-surface-variant hover:border-primary/40"
                  }`}
                >
                  <span className="material-symbols-outlined text-base">{opt.icon}</span>
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Ngân sách */}
          <div>
            <label className="block text-sm font-medium text-on-surface mb-1.5">Ngân sách</label>
            <div className="flex flex-wrap gap-2">
              {BUDGET_LEVELS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setBudgetLevel((b) => (b === opt.value ? "" : opt.value))}
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm border transition-colors ${
                    budgetLevel === opt.value
                      ? "bg-primary-container text-on-primary-container border-primary"
                      : "border-outline-variant/40 text-on-surface-variant hover:border-primary/40"
                  }`}
                >
                  <span className="material-symbols-outlined text-base">{opt.icon}</span>
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Sở thích */}
          <div>
            <label className="block text-sm font-medium text-on-surface mb-1.5">Sở thích</label>
            <div className="flex flex-wrap gap-2">
              {INTERESTS.map((opt) => {
                const active = interests.includes(opt.value);
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleInterest(opt.value)}
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm border transition-colors ${
                      active
                        ? "bg-primary-container text-on-primary-container border-primary"
                        : "border-outline-variant/40 text-on-surface-variant hover:border-primary/40"
                    }`}
                  >
                    <span className="material-symbols-outlined text-base">{opt.icon}</span>
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Ăn kiêng */}
          <div>
            <label className="block text-sm font-medium text-on-surface mb-1.5">Ăn kiêng / lưu ý ẩm thực</label>
            <input
              className={inputCls}
              value={dietary}
              onChange={(e) => setDietary(e.target.value)}
              placeholder="Vd: ăn chay, không hải sản"
              maxLength={200}
            />
          </div>

          {/* Ngôn ngữ */}
          <div>
            <label className="block text-sm font-medium text-on-surface mb-1.5">Ngôn ngữ</label>
            <select className={inputCls} value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
              {LANGUAGES.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <Button onClick={handleSave} disabled={!sessionId || upsert.isPending}>
              {upsert.isPending ? "Đang lưu…" : "Lưu hồ sơ"}
            </Button>
            <Button variant="ghost" onClick={handleClear} disabled={!sessionId || del.isPending}>
              Xoá hồ sơ
            </Button>
            <Link href="/recommend" className="ml-auto text-sm text-primary hover:underline">
              Xem gợi ý →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
