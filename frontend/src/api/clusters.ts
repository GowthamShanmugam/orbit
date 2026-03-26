import type { CreateClusterInput, ProjectCluster } from "@/types";
import { apiClient } from "./client";

export async function listClusters(
  projectId: string,
  role?: string,
): Promise<ProjectCluster[]> {
  const params = role ? { role } : {};
  const { data } = await apiClient.get<ProjectCluster[]>(
    `/projects/${projectId}/clusters`,
    { params },
  );
  return data;
}

export async function getCluster(
  projectId: string,
  clusterId: string,
): Promise<ProjectCluster> {
  const { data } = await apiClient.get<ProjectCluster>(
    `/projects/${projectId}/clusters/${clusterId}`,
  );
  return data;
}

export async function createCluster(
  projectId: string,
  input: CreateClusterInput,
): Promise<ProjectCluster> {
  const { data } = await apiClient.post<ProjectCluster>(
    `/projects/${projectId}/clusters`,
    input,
  );
  return data;
}

export async function deleteCluster(
  projectId: string,
  clusterId: string,
): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/clusters/${clusterId}`);
}

export async function testConnection(
  projectId: string,
  clusterId: string,
): Promise<{ connected: boolean; message: string }> {
  const { data } = await apiClient.post<{
    connected: boolean;
    message: string;
  }>(`/projects/${projectId}/clusters/${clusterId}/test-connection`);
  return data;
}
