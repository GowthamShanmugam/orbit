import type {
  CreateMappingInput,
  DeploymentInfo,
  MappingSuggestion,
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

export async function deleteSystemMap(projectId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/system-map`);
}
