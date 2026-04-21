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

// ── Global AI rules ──────────────────────────────────────────────────────────

export async function listGlobalAIRules(): Promise<AIRule[]> {
  const { data } = await apiClient.get("/settings/ai-rules");
  return data;
}

export async function createGlobalAIRule(input: CreateRuleInput): Promise<AIRule> {
  const { data } = await apiClient.post("/settings/ai-rules", input);
  return data;
}

export async function updateGlobalAIRule(ruleId: string, input: UpdateRuleInput): Promise<AIRule> {
  const { data } = await apiClient.patch(`/settings/ai-rules/${ruleId}`, input);
  return data;
}

export async function deleteGlobalAIRule(ruleId: string): Promise<void> {
  await apiClient.delete(`/settings/ai-rules/${ruleId}`);
}

// ── Project-scoped AI rules ─────────────────────────────────────────────────

export async function listProjectAIRules(projectId: string): Promise<AIRule[]> {
  const { data } = await apiClient.get(`/projects/${projectId}/ai-rules`);
  return data;
}

export async function createProjectAIRule(
  projectId: string,
  input: CreateRuleInput,
): Promise<AIRule> {
  const { data } = await apiClient.post(`/projects/${projectId}/ai-rules`, input);
  return data;
}

export async function updateProjectAIRule(
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

export async function deleteProjectAIRule(
  projectId: string,
  ruleId: string,
): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/ai-rules/${ruleId}`);
}

// ── Global feature flags ────────────────────────────────────────────────────

export async function getFeatureFlags(): Promise<Record<string, boolean>> {
  const { data } = await apiClient.get("/settings/feature-flags");
  return data;
}

export async function putFeatureFlags(
  flags: Record<string, boolean>,
): Promise<Record<string, boolean>> {
  const { data } = await apiClient.put("/settings/feature-flags", flags);
  return data;
}
