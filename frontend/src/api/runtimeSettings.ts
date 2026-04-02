import { apiClient } from "./client";

export type RuntimeSettingsPayload = {
  values: Record<string, number>;
  env_defaults: Record<string, number>;
  overridden_keys: string[];
  allow_write: boolean;
};

export type RuntimeSettingsUpdate = Partial<{
  AI_MAX_TOOL_ROUNDS: number | null;
  AI_CONTEXT_ASSEMBLY_MAX_TOKENS: number | null;
  AI_MAX_CONTINUATIONS: number | null;
  AI_TOOL_SSE_HEARTBEAT_SEC: number | null;
  MCP_TOOL_CALL_TIMEOUT_SEC: number | null;
  MCP_CONNECTION_TIMEOUT_SEC: number | null;
  LOCAL_TOOL_DEFAULT_TIMEOUT_SEC: number | null;
  LOCAL_TOOL_MAX_TIMEOUT_SEC: number | null;
}>;

export async function getRuntimeSettings(): Promise<RuntimeSettingsPayload> {
  const { data } = await apiClient.get<RuntimeSettingsPayload>("/settings/runtime");
  return data;
}

export async function putRuntimeSettings(
  body: RuntimeSettingsUpdate,
): Promise<RuntimeSettingsPayload> {
  const { data } = await apiClient.put<RuntimeSettingsPayload>("/settings/runtime", body);
  return data;
}
