import type { ChatInput, StreamEvent, Thread, ThreadDetail } from "@/types";
import { streamSSE } from "@/lib/sseStream";
import { apiClient } from "./client";

export interface CreateThreadInput {
  parent_message_id: string;
  claude_model?: string;
  ai_config?: Record<string, unknown>;
}

export interface UpdateThreadInput {
  title?: string;
  claude_model?: string;
  ai_config?: Record<string, unknown>;
}

export async function createThread(
  projectId: string,
  sessionId: string,
  input: CreateThreadInput,
): Promise<Thread> {
  const { data } = await apiClient.post<Thread>(
    `/projects/${projectId}/sessions/${sessionId}/threads`,
    input,
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

export async function updateThread(
  projectId: string,
  sessionId: string,
  threadId: string,
  input: UpdateThreadInput,
): Promise<Thread> {
  const { data } = await apiClient.patch<Thread>(
    `/projects/${projectId}/sessions/${sessionId}/threads/${threadId}`,
    input,
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
