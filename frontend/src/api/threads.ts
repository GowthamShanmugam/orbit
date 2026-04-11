import type { ChatInput, Message, StreamEvent, Thread, ThreadDetail } from "@/types";
import { handleSessionExpired } from "@/lib/authSession";
import { apiClient, getStoredToken } from "./client";

export async function createThread(
  projectId: string,
  sessionId: string,
  parentMessageId: string,
): Promise<Thread> {
  const { data } = await apiClient.post<Thread>(
    `/projects/${projectId}/sessions/${sessionId}/threads`,
    { parent_message_id: parentMessageId },
  );
  return data;
}

export async function listThreads(
  projectId: string,
  sessionId: string,
): Promise<Thread[]> {
  const { data } = await apiClient.get<Thread[]>(
    `/projects/${projectId}/sessions/${sessionId}/threads`,
  );
  return data;
}

export async function getThread(
  projectId: string,
  sessionId: string,
  threadId: string,
): Promise<ThreadDetail> {
  const { data } = await apiClient.get<ThreadDetail>(
    `/projects/${projectId}/sessions/${sessionId}/threads/${threadId}`,
  );
  return data;
}

export async function deleteThread(
  projectId: string,
  sessionId: string,
  threadId: string,
): Promise<void> {
  await apiClient.delete(
    `/projects/${projectId}/sessions/${sessionId}/threads/${threadId}`,
  );
}

export async function* streamThreadChat(
  projectId: string,
  sessionId: string,
  threadId: string,
  input: ChatInput,
): AsyncGenerator<StreamEvent> {
  const token = getStoredToken();
  const baseUrl = apiClient.defaults.baseURL ?? "/api";
  const url = `${baseUrl}/projects/${projectId}/sessions/${sessionId}/threads/${threadId}/chat`;

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
    throw new Error(`Thread chat request failed (${res.status}): ${text}`);
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
