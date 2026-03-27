import type { AIModel, ChatInput, StreamEvent } from "@/types";
import { apiClient, getStoredToken } from "./client";

export async function listModels(): Promise<AIModel[]> {
  const { data } = await apiClient.get<AIModel[]>("/ai/models");
  return data;
}

/**
 * Stream a chat response via SSE.
 *
 * Returns an async iterator that yields parsed SSE events from the
 * `/projects/:pid/sessions/:sid/chat` endpoint.
 */
export async function* streamChat(
  projectId: string,
  sessionId: string,
  input: ChatInput,
): AsyncGenerator<StreamEvent> {
  const token = getStoredToken();
  const baseUrl = apiClient.defaults.baseURL ?? "/api";
  const url = `${baseUrl}/projects/${projectId}/sessions/${sessionId}/chat`;

  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(input),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Chat request failed (${res.status}): ${text}`);
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
          // skip malformed JSON
        }
        currentEvent = "";
      }
    }
  }
}
