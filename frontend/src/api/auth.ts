import type { LoginRequest, LoginResponse, User } from "@/types";
import { apiClient } from "./client";

export async function login(body: LoginRequest): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>("/auth/login", body);
  return data;
}

export async function getMe(): Promise<User> {
  const { data } = await apiClient.get<User>("/auth/me");
  return data;
}

export type AuthMode = "ocp" | "sso" | "dev";

export interface AuthModeInfo {
  mode: AuthMode;
  /** Relative path — only if oauth-proxy handles it before the SPA */
  ocpSignoutPath: string | null;
  /** Full IdP logout URL (optional), takes precedence over path */
  ocpSignoutUrl: string | null;
}

export async function getAuthMode(): Promise<AuthModeInfo> {
  const { data } = await apiClient.get<{
    mode: AuthMode;
    ocp_signout_path?: string | null;
    ocp_signout_url?: string | null;
  }>("/auth/mode");
  return {
    mode: data.mode,
    ocpSignoutPath: data.ocp_signout_path ?? null,
    ocpSignoutUrl: data.ocp_signout_url ?? null,
  };
}

export interface WhoamiResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export async function whoami(): Promise<WhoamiResponse> {
  const { data } = await apiClient.get<WhoamiResponse>("/auth/whoami");
  return data;
}
