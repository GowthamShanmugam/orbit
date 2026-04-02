import type {
  CreateSessionInput,
  Message,
  SendMessageInput,
  Session,
  UpdateSessionInput,
} from "@/types";
import { apiClient } from "./client";

export async function listSessions(
  projectId: string,
): Promise<Session[]> {
  const { data } = await apiClient.get<Session[]>(
    `/projects/${projectId}/sessions`,
  );
  return data;
}

export async function createSession(
  projectId: string,
  input: CreateSessionInput
): Promise<Session> {
  const { data } = await apiClient.post<Session>(
    `/projects/${projectId}/sessions`,
    input
  );
  return data;
}

export async function getSession(
  projectId: string,
  sessionId: string
): Promise<Session> {
  const { data } = await apiClient.get<Session>(
    `/projects/${projectId}/sessions/${sessionId}`
  );
  return data;
}

export async function updateSession(
  projectId: string,
  sessionId: string,
  input: UpdateSessionInput
): Promise<Session> {
  const { data } = await apiClient.patch<Session>(
    `/projects/${projectId}/sessions/${sessionId}`,
    input
  );
  return data;
}

export async function deleteSession(
  projectId: string,
  sessionId: string
): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/sessions/${sessionId}`);
}

export async function listMessages(
  projectId: string,
  sessionId: string,
  params?: { page?: number; page_size?: number }
): Promise<Message[]> {
  const { data } = await apiClient.get<Message[]>(
    `/projects/${projectId}/sessions/${sessionId}/messages`,
    { params }
  );
  return data;
}

export async function sendMessage(
  projectId: string,
  sessionId: string,
  input: SendMessageInput
): Promise<Message> {
  const { data } = await apiClient.post<Message>(
    `/projects/${projectId}/sessions/${sessionId}/messages`,
    { role: "user", ...input },
  );
  return data;
}
