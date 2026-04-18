import type { ChatInput, StreamEvent } from "@/types";
import { streamSSE } from "@/lib/sseStream";
import { apiClient } from "./client";

export async function confirmTool(
  projectId: string,
  sessionId: string,
  toolId: string,
  approved: boolean,
): Promise<void> {
  await apiClient.post(
    `/projects/${projectId}/sessions/${sessionId}/confirm-tool`,
    { tool_id: toolId, approved },
  );
}

export async function* streamChat(
  projectId: string,
  sessionId: string,
  input: ChatInput,
): AsyncGenerator<StreamEvent> {
  yield* streamSSE(
    `/projects/${projectId}/sessions/${sessionId}/chat`,
    input,
    "Chat request",
  );
}
