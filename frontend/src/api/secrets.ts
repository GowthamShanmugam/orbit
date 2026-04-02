import type {
  CreateSecretInput,
  ProjectSecret,
  RotateSecretInput,
  ScanResponse,
  SecretAuditEntry,
} from "@/types";
import { apiClient } from "./client";

export async function listSecrets(projectId: string): Promise<ProjectSecret[]> {
  const { data } = await apiClient.get<ProjectSecret[]>(
    `/projects/${projectId}/secrets`,
  );
  return data;
}

export async function createSecret(
  projectId: string,
  input: CreateSecretInput,
): Promise<ProjectSecret> {
  const { data } = await apiClient.post<ProjectSecret>(
    `/projects/${projectId}/secrets`,
    input,
  );
  return data;
}

export async function rotateSecret(
  projectId: string,
  secretId: string,
  input: RotateSecretInput,
): Promise<ProjectSecret> {
  const { data } = await apiClient.put<ProjectSecret>(
    `/projects/${projectId}/secrets/${secretId}`,
    input,
  );
  return data;
}

export async function deleteSecret(
  projectId: string,
  secretId: string,
): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/secrets/${secretId}`);
}

export async function getAuditLog(
  projectId: string,
  secretId: string,
): Promise<SecretAuditEntry[]> {
  const { data } = await apiClient.get<SecretAuditEntry[]>(
    `/projects/${projectId}/secrets/${secretId}/audit`,
  );
  return data;
}

export async function scanForSecrets(text: string): Promise<ScanResponse> {
  const { data } = await apiClient.post<ScanResponse>("/scan-secrets", {
    text,
  });
  return data;
}
