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
  visibility?: "public" | "private";
}): Promise<ImportResult> {
  const { data } = await apiClient.post<ImportResult>("/skills/import-github", input);
  return data;
}
