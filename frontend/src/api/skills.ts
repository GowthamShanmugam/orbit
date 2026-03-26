import type { McpSkill, McpSkillConfigInput, McpSkillCreateInput, SkillTestResult } from "@/types";
import { apiClient } from "./client";

export async function listSkills(): Promise<McpSkill[]> {
  const { data } = await apiClient.get<McpSkill[]>("/skills");
  return data;
}

export async function getSkill(skillId: string): Promise<McpSkill> {
  const { data } = await apiClient.get<McpSkill>(`/skills/${skillId}`);
  return data;
}

export async function createSkill(input: McpSkillCreateInput): Promise<McpSkill> {
  const { data } = await apiClient.post<McpSkill>("/skills", input);
  return data;
}

export async function configureSkill(
  skillId: string,
  input: McpSkillConfigInput,
): Promise<McpSkill> {
  const { data } = await apiClient.put<McpSkill>(
    `/skills/${skillId}/configure`,
    input,
  );
  return data;
}

export async function toggleSkill(skillId: string): Promise<McpSkill> {
  const { data } = await apiClient.put<McpSkill>(`/skills/${skillId}/toggle`);
  return data;
}

export async function testSkillConnection(
  skillId: string,
): Promise<SkillTestResult> {
  const { data } = await apiClient.post<SkillTestResult>(
    `/skills/${skillId}/test`,
  );
  return data;
}

export async function refreshSkillTools(skillId: string): Promise<McpSkill> {
  const { data } = await apiClient.post<McpSkill>(
    `/skills/${skillId}/refresh`,
  );
  return data;
}

export async function deleteSkill(skillId: string): Promise<void> {
  await apiClient.delete(`/skills/${skillId}`);
}
