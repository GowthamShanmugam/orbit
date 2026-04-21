import { apiClient } from "./client";

export interface AIRule {
  id: string;
  scope: string;
  category: string;
  project_id: string | null;
  title: string;
  content: string;
  enabled: boolean;
  is_seeded: boolean;
  sort_order: number;
  readonly: boolean;
}

export interface CreateRuleInput {
  title: string;
  content: string;
  category?: string;
  sort_order?: number;
}

export interface UpdateRuleInput {
  title?: string;
  content?: string;
  category?: string;
  enabled?: boolean;
  sort_order?: number;
}

export async function listAIRules(projectId: string): Promise<AIRule[]> {
  const { data } = await apiClient.get(`/projects/${projectId}/ai-rules`);
  return data;
}

export async function createAIRule(
  projectId: string,
  input: CreateRuleInput,
): Promise<AIRule> {
  const { data } = await apiClient.post(`/projects/${projectId}/ai-rules`, input);
  return data;
}

export async function updateAIRule(
  projectId: string,
  ruleId: string,
  input: UpdateRuleInput,
): Promise<AIRule> {
  const { data } = await apiClient.patch(
    `/projects/${projectId}/ai-rules/${ruleId}`,
    input,
  );
  return data;
}

export async function deleteAIRule(
  projectId: string,
  ruleId: string,
): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/ai-rules/${ruleId}`);
}
