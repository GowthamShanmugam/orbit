import type {
  CreateProjectInput,
  CreateProjectShareInput,
  Project,
  ProjectShare,
  ShareableUser,
  UpdateProjectInput,
} from "@/types";
import { apiClient } from "./client";

export async function listProjects(): Promise<Project[]> {
  const { data } = await apiClient.get<Project[]>("/projects");
  return data;
}

export async function createProject(
  input: CreateProjectInput
): Promise<Project> {
  const { data } = await apiClient.post<Project>("/projects", input);
  return data;
}

export async function getProject(id: string): Promise<Project> {
  const { data } = await apiClient.get<Project>(`/projects/${id}`);
  return data;
}

export async function updateProject(
  id: string,
  input: UpdateProjectInput
): Promise<Project> {
  const { data } = await apiClient.put<Project>(`/projects/${id}`, input);
  return data;
}

export async function deleteProject(id: string): Promise<void> {
  await apiClient.delete(`/projects/${id}`);
}

export async function listProjectShares(
  projectId: string,
): Promise<ProjectShare[]> {
  const { data } = await apiClient.get<ProjectShare[]>(
    `/projects/${projectId}/shares`,
  );
  return data;
}

export async function listShareableUsers(
  projectId: string,
): Promise<ShareableUser[]> {
  const { data } = await apiClient.get<ShareableUser[]>(
    `/projects/${projectId}/shareable-users`,
  );
  return data;
}

export async function createProjectShare(
  projectId: string,
  input: CreateProjectShareInput,
): Promise<ProjectShare> {
  const { data } = await apiClient.post<ProjectShare>(
    `/projects/${projectId}/shares`,
    input,
  );
  return data;
}

export async function patchProjectShare(
  projectId: string,
  shareId: string,
  role: ProjectShare["role"],
): Promise<ProjectShare> {
  const { data } = await apiClient.patch<ProjectShare>(
    `/projects/${projectId}/shares/${shareId}`,
    { role },
  );
  return data;
}

export async function deleteProjectShare(
  projectId: string,
  shareId: string,
): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/shares/${shareId}`);
}
