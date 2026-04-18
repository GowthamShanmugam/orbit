import type {
  CreateSecretInput,
  ProjectSecret,
  RotateSecretInput,
  ScanResponse,
  SecretAuditEntry,
} from "@/types";
import { apiClient } from "./client";

export async function listSecrets(): Promise<ProjectSecret[]> {
  const { data } = await apiClient.get<ProjectSecret[]>("/secrets");
  return data;
}

export async function createSecret(input: CreateSecretInput): Promise<ProjectSecret> {
  const { data } = await apiClient.post<ProjectSecret>("/secrets", input);
  return data;
}

export async function rotateSecret(
  secretId: string,
  input: RotateSecretInput,
): Promise<ProjectSecret> {
  const { data } = await apiClient.put<ProjectSecret>(`/secrets/${secretId}`, input);
  return data;
}

export async function deleteSecret(secretId: string): Promise<void> {
  await apiClient.delete(`/secrets/${secretId}`);
}

export async function getAuditLog(secretId: string): Promise<SecretAuditEntry[]> {
  const { data } = await apiClient.get<SecretAuditEntry[]>(`/secrets/${secretId}/audit`);
  return data;
}

export async function scanForSecrets(text: string): Promise<ScanResponse> {
  const { data } = await apiClient.post<ScanResponse>("/scan-secrets", { text });
  return data;
}
