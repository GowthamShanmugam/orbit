import type {
  ContextPack,
  CreatePackInput,
  InstalledPack,
  UpdatePackInput,
} from "@/types";
import { apiClient } from "./client";

export async function listPacks(params?: {
  category?: string;
  search?: string;
  skip?: number;
  limit?: number;
}): Promise<ContextPack[]> {
  const { data } = await apiClient.get<ContextPack[]>("/hub/packs", { params });
  return data;
}

export async function getPack(packId: string): Promise<ContextPack> {
  const { data } = await apiClient.get<ContextPack>(`/hub/packs/${packId}`);
  return data;
}

export async function createPack(input: CreatePackInput): Promise<ContextPack> {
  const { data } = await apiClient.post<ContextPack>("/hub/packs", input);
  return data;
}

export async function updatePack(
  packId: string,
  input: UpdatePackInput,
): Promise<ContextPack> {
  const { data } = await apiClient.put<ContextPack>(
    `/hub/packs/${packId}`,
    input,
  );
  return data;
}

export async function deletePack(packId: string): Promise<void> {
  await apiClient.delete(`/hub/packs/${packId}`);
}

export async function listCategories(): Promise<string[]> {
  const { data } = await apiClient.get<string[]>("/hub/packs/categories");
  return data;
}

export async function listInstalledPacks(
  projectId: string,
): Promise<InstalledPack[]> {
  const { data } = await apiClient.get<InstalledPack[]>(
    `/hub/projects/${projectId}/installed-packs`,
  );
  return data;
}

export async function installPack(
  projectId: string,
  packId: string,
  autoUpdate = true,
): Promise<InstalledPack> {
  const { data } = await apiClient.post<InstalledPack>(
    `/hub/projects/${projectId}/installed-packs`,
    { pack_id: packId, auto_update: autoUpdate },
  );
  return data;
}

export async function uninstallPack(
  projectId: string,
  packId: string,
): Promise<void> {
  await apiClient.delete(
    `/hub/projects/${projectId}/installed-packs/${packId}`,
  );
}
