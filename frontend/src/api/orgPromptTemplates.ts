import { apiClient } from "./client";
import type { OrgPromptTemplate, OrgPromptTemplatesListResponse } from "@/types";

export async function listOrgPromptTemplates(
  orgId: string,
): Promise<OrgPromptTemplatesListResponse> {
  const { data } = await apiClient.get<OrgPromptTemplatesListResponse>(
    `/organizations/${orgId}/prompt-templates`,
  );
  return data;
}

export async function createOrgPromptTemplate(
  orgId: string,
  input: { title: string; body: string; sort_order?: number },
): Promise<OrgPromptTemplate> {
  const { data } = await apiClient.post<OrgPromptTemplate>(
    `/organizations/${orgId}/prompt-templates`,
    input,
  );
  return data;
}

export async function updateOrgPromptTemplate(
  orgId: string,
  templateId: string,
  input: { title?: string; body?: string; sort_order?: number },
): Promise<OrgPromptTemplate> {
  const { data } = await apiClient.patch<OrgPromptTemplate>(
    `/organizations/${orgId}/prompt-templates/${templateId}`,
    input,
  );
  return data;
}

export async function deleteOrgPromptTemplate(
  orgId: string,
  templateId: string,
): Promise<void> {
  await apiClient.delete(
    `/organizations/${orgId}/prompt-templates/${templateId}`,
  );
}
