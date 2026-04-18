import type {
  PluginConfigInput,
  SkillCategoryInfo,
  SkillPlugin,
  SkillTestResult,
  Integration,
} from "@/types";
import { apiClient } from "./client";

// ===========================================================================
// Integrations API (per-user MCP tools)
// ===========================================================================

export async function listIntegrations(): Promise<{
  integrations: Integration[];
  canManage: boolean;
}> {
  const { data } = await apiClient.get<{
    integrations: Integration[];
    can_manage: boolean;
  }>("/integrations");
  return {
    integrations: data.integrations,
    canManage: data.can_manage,
  };
}

export async function configureIntegration(
  pluginId: string,
  input: PluginConfigInput,
): Promise<Integration> {
  const { data } = await apiClient.put<Integration>(`/integrations/${pluginId}/configure`, input);
  return data;
}

export async function testIntegration(pluginId: string): Promise<SkillTestResult> {
  const { data } = await apiClient.post<SkillTestResult>(`/integrations/${pluginId}/test`);
  return data;
}

// ===========================================================================
// OAuth flow (Google Drive etc.)
// ===========================================================================

export async function startGoogleDriveOAuth(clientJson: string): Promise<{
  auth_url: string;
  callback_url: string;
}> {
  const { data } = await apiClient.post<{ auth_url: string; callback_url: string }>(
    "/oauth/google-drive/start",
    { client_json: clientJson },
  );
  return data;
}

// ===========================================================================
// Skills API (public prompt packs -- no install needed)
// ===========================================================================

export async function listSkills(): Promise<{
  skills: SkillPlugin[];
  categories: SkillCategoryInfo[];
}> {
  const { data } = await apiClient.get<{
    skills: SkillPlugin[];
    categories: SkillCategoryInfo[];
  }>("/skills");
  return { skills: data.skills, categories: data.categories };
}

export async function deleteSkillPack(pluginId: string): Promise<void> {
  await apiClient.delete(`/skills/${pluginId}`);
}

export interface ImportResult {
  imported: SkillPlugin[];
  skipped: string[];
  total: number;
}

export async function importSkillFromGitHub(input: {
  repo_url: string;
  name?: string;
  category_slug?: string;
}): Promise<ImportResult> {
  const { data } = await apiClient.post<ImportResult>("/skills/import-github", input);
  return data;
}

// ===========================================================================
// Project-scoped Skills API
// ===========================================================================

export type ProjectSkillPlugin = SkillPlugin & { installed: boolean };

export async function listProjectSkills(projectId: string): Promise<{
  skills: ProjectSkillPlugin[];
  categories: SkillCategoryInfo[];
}> {
  const { data } = await apiClient.get<{
    skills: ProjectSkillPlugin[];
    categories: SkillCategoryInfo[];
  }>(`/projects/${projectId}/skills`);
  return { skills: data.skills, categories: data.categories };
}

export async function listAvailableSkills(projectId: string): Promise<{
  skills: SkillPlugin[];
}> {
  const { data } = await apiClient.get<{ skills: SkillPlugin[] }>(
    `/projects/${projectId}/skills/available`,
  );
  return { skills: data.skills };
}

export async function installSkillToProject(
  projectId: string,
  pluginId: string,
): Promise<ProjectSkillPlugin> {
  const { data } = await apiClient.post<ProjectSkillPlugin>(
    `/projects/${projectId}/skills/${pluginId}/install`,
  );
  return data;
}

export async function uninstallSkillFromProject(
  projectId: string,
  pluginId: string,
): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/skills/${pluginId}/uninstall`);
}
