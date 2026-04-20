import type {
  CreateEdgeInput,
  CreateMappingInput,
  DeploymentInfo,
  HierarchyEdge,
  MappingSuggestion,
  MapStatusItem,
  NodePosition,
  ServiceEdgeResponse,
  ServiceMappingResponse,
} from "@/types";
import { apiClient } from "./client";

export async function getDeployments(projectId: string): Promise<DeploymentInfo[]> {
  const { data } = await apiClient.get<DeploymentInfo[]>(
    `/projects/${projectId}/system-map/deployments`,
  );
  return data;
}

export async function suggestMappings(projectId: string): Promise<MappingSuggestion[]> {
  const { data } = await apiClient.post<MappingSuggestion[]>(
    `/projects/${projectId}/system-map/suggest`,
  );
  return data;
}

export async function getMappings(projectId: string): Promise<ServiceMappingResponse[]> {
  const { data } = await apiClient.get<ServiceMappingResponse[]>(
    `/projects/${projectId}/system-map/mappings`,
  );
  return data;
}

export async function saveMappings(
  projectId: string,
  mappings: CreateMappingInput[],
): Promise<ServiceMappingResponse[]> {
  const { data } = await apiClient.post<ServiceMappingResponse[]>(
    `/projects/${projectId}/system-map/mappings`,
    { mappings },
  );
  return data;
}

export async function updateMapping(
  projectId: string,
  mappingId: string,
  updates: Partial<CreateMappingInput>,
): Promise<ServiceMappingResponse> {
  const { data } = await apiClient.put<ServiceMappingResponse>(
    `/projects/${projectId}/system-map/mappings/${mappingId}`,
    updates,
  );
  return data;
}

export async function deleteMapping(projectId: string, mappingId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/system-map/mappings/${mappingId}`);
}

export async function getMapStatus(projectId: string): Promise<MapStatusItem[]> {
  const { data } = await apiClient.get<MapStatusItem[]>(
    `/projects/${projectId}/system-map/status`,
  );
  return data;
}

export async function getHierarchy(projectId: string): Promise<HierarchyEdge[]> {
  const { data } = await apiClient.get<HierarchyEdge[]>(
    `/projects/${projectId}/system-map/hierarchy`,
  );
  return data;
}

export async function getEdges(projectId: string): Promise<ServiceEdgeResponse[]> {
  const { data } = await apiClient.get<ServiceEdgeResponse[]>(
    `/projects/${projectId}/system-map/edges`,
  );
  return data;
}

export async function createEdge(
  projectId: string,
  edge: CreateEdgeInput,
): Promise<ServiceEdgeResponse> {
  const { data } = await apiClient.post<ServiceEdgeResponse>(
    `/projects/${projectId}/system-map/edges`,
    edge,
  );
  return data;
}

export async function deleteEdge(projectId: string, edgeId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/system-map/edges/${edgeId}`);
}

export async function savePositions(
  projectId: string,
  positions: NodePosition[],
): Promise<void> {
  await apiClient.put(`/projects/${projectId}/system-map/positions`, { positions });
}

export interface ServiceDetail {
  events: {
    type: string;
    reason: string;
    message: string;
    object: string;
    count: number;
    last_seen: string | null;
  }[];
  pods: {
    name: string;
    phase: string;
    ready: number;
    total: number;
    restarts: number;
  }[];
  logs: string;
}

export async function getServiceDetail(
  projectId: string,
  mappingId: string,
): Promise<ServiceDetail> {
  const { data } = await apiClient.get<ServiceDetail>(
    `/projects/${projectId}/system-map/mappings/${mappingId}/detail`,
  );
  return data;
}

export async function createDebugSession(
  projectId: string,
  mappingId: string,
  prompt?: string,
): Promise<{ session_id: string }> {
  const { data } = await apiClient.post<{ session_id: string }>(
    `/projects/${projectId}/system-map/mappings/${mappingId}/debug-session`,
    { prompt },
  );
  return data;
}
