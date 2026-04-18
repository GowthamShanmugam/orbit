import type { ChatInput, StreamEvent } from "@/types";
import { handleSessionExpired } from "@/lib/authSession";
import { apiClient, getStoredToken } from "@/api/client";

/**
 * Generic SSE streaming helper.
 * Sends a POST with JSON body and yields parsed SSE events.
 */
export async function* streamSSE(
  path: string,
  input: ChatInput,
  errorPrefix = "Request",
): AsyncGenerator<StreamEvent> {
  const token = getStoredToken();
  const baseUrl = apiClient.defaults.baseURL ?? "/api";
  const url = `${baseUrl}${path}`;

  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(input),
  });

  if (res.status === 401) {
    handleSessionExpired();
    throw new Error("Session expired. Sign in again.");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${errorPrefix} failed (${res.status}): ${text}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    let currentEvent = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ") && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          yield { type: currentEvent, ...data } as StreamEvent;
        } catch {
          /* skip malformed JSON */
        }
        currentEvent = "";
      }
    }
  }
}
