import type { ChatInput, StreamEvent, Thread, ThreadDetail } from "@/types";
import { streamSSE } from "@/lib/sseStream";
import { apiClient } from "./client";

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

export async function listThreads(projectId: string, sessionId: string): Promise<Thread[]> {
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

export async function* streamThreadChat(
  projectId: string,
  sessionId: string,
  threadId: string,
  input: ChatInput,
): AsyncGenerator<StreamEvent> {
  yield* streamSSE(
    `/projects/${projectId}/sessions/${sessionId}/threads/${threadId}/chat`,
    input,
    "Thread chat request",
  );
}
