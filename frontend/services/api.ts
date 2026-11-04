import type { AgentEvent } from "@/types";

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed. Check your input.");
  return data as T;
}

export async function streamChat(body: object, signal: AbortSignal, onEvent: (event: AgentEvent) => void) {
  const response = await fetch("/api/chat/stream", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
  });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || "Could not start the agent run.");
  }
  if (!response.body) throw new Error("Streaming is unavailable in this browser.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let receivedResult = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = frame.split("\n").filter(line => line.startsWith("data: ")).map(line => line.slice(6)).join("\n");
        if (data) {
          const event = JSON.parse(data) as AgentEvent;
          if (event.type === "result") receivedResult = true;
          onEvent(event);
        }
      }
      if (done) break;
    }
  } finally { reader.releaseLock(); }
  if (!receivedResult) throw new Error("Connection ended before a result was received. Try again.");
}
