// Xuất lịch trình ra file Markdown (client-side, không cần backend/thư viện).
export function downloadMarkdown(title: string, content: string): void {
  if (typeof window === "undefined") return;
  const slug =
    title
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/đ/g, "d")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "lich-trinh";
  // content_md thường đã có heading riêng → không prepend title (tránh trùng); title nằm ở tên file.
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${slug}.md`;
  a.click();
  URL.revokeObjectURL(url);
}
