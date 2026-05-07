export type SSEEventType = "meta" | "intent" | "sources" | "token" | "done" | "error" | "waiting";

export interface SSEEvent {
  type: SSEEventType;
  data: Record<string, unknown>;
}

function parseChunk(chunk: string): SSEEvent | null {
  const lines = chunk.split("\n");
  let eventType: SSEEventType = "token";
  let dataStr = "";
  for (const line of lines) {
    if (line.startsWith("event: ")) eventType = line.slice(7).trim() as SSEEventType;
    if (line.startsWith("data: ")) dataStr = line.slice(6).trim();
  }
  if (!dataStr) return null;
  try {
    return { type: eventType, data: JSON.parse(dataStr) };
  } catch {
    return null;
  }
}

export async function* streamSSE(
  url: string,
  body: object,
  signal: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${BASE}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`Stream error: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const event = parseChunk(chunk);
      if (event) yield event;
    }
  }
}
