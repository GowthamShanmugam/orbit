import type {
  AddContextSourceInput,
  AddSessionLayerInput,
  ContextSource,
  SessionLayer,
} from "@/types";
import { apiClient } from "./client";


export async function listContextSources(
  projectId: string,
): Promise<ContextSource[]> {
  const { data } = await apiClient.get<ContextSource[]>(
    `/projects/${projectId}/context-sources`,
  );
  return data;
}

export async function addContextSource(
  projectId: string,
  input: AddContextSourceInput,
): Promise<ContextSource> {
  const { data } = await apiClient.post<ContextSource>(
    `/projects/${projectId}/context-sources`,
    input,
  );
  return data;
}

export async function removeContextSource(
  projectId: string,
  sourceId: string,
): Promise<void> {
  await apiClient.delete(
    `/projects/${projectId}/context-sources/${sourceId}`,
  );
}

export async function listSessionLayers(
  sessionId: string,
): Promise<SessionLayer[]> {
  const { data } = await apiClient.get<SessionLayer[]>(
    `/sessions/${sessionId}/layers`,
  );
  return data;
}

export async function addSessionLayer(
  sessionId: string,
  input: AddSessionLayerInput,
): Promise<SessionLayer> {
  const { data } = await apiClient.post<SessionLayer>(
    `/sessions/${sessionId}/layers`,
    input,
  );
  return data;
}

export async function removeSessionLayer(
  sessionId: string,
  layerId: string,
): Promise<void> {
  await apiClient.delete(`/sessions/${sessionId}/layers/${layerId}`);
}


export async function cloneRepoSource(
  sourceId: string,
): Promise<{ status: string }> {
  const { data } = await apiClient.post<{ status: string }>(
    `/context-sources/${sourceId}/clone`,
  );
  return data;
}
