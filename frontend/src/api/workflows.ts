import type { CreateWorkflowInput, Workflow } from "@/types";
import { apiClient } from "./client";

export async function listWorkflows(): Promise<Workflow[]> {
  const { data } = await apiClient.get<Workflow[]>("/workflows");
  return data;
}

export async function getWorkflow(slug: string): Promise<Workflow> {
  const { data } = await apiClient.get<Workflow>(`/workflows/${slug}`);
  return data;
}

export async function createWorkflow(input: CreateWorkflowInput): Promise<Workflow> {
  const { data } = await apiClient.post<Workflow>("/workflows", input);
  return data;
}

export async function deleteWorkflow(workflowId: string): Promise<void> {
  await apiClient.delete(`/workflows/${workflowId}`);
}
