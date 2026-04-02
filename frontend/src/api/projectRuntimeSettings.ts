import { apiClient } from "./client";
import type { RuntimeSettingsUpdate } from "./runtimeSettings";

export type ProjectRuntimeSettingsPayload = {
  values: Record<string, number>;
  global_values: Record<string, number>;
  project_overrides: Record<string, number>;
  env_defaults: Record<string, number>;
  project_override_keys: string[];
  allow_write: boolean;
};

export async function getProjectRuntimeSettings(
  projectId: string,
): Promise<ProjectRuntimeSettingsPayload> {
  const { data } = await apiClient.get<ProjectRuntimeSettingsPayload>(
    `/projects/${projectId}/runtime-settings`,
  );
  return data;
}

export async function putProjectRuntimeSettings(
  projectId: string,
  body: RuntimeSettingsUpdate,
): Promise<ProjectRuntimeSettingsPayload> {
  const { data } = await apiClient.put<ProjectRuntimeSettingsPayload>(
    `/projects/${projectId}/runtime-settings`,
    body,
  );
  return data;
}
