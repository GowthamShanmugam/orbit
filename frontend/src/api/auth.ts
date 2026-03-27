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

export async function getAuthMode(): Promise<AuthMode> {
  const { data } = await apiClient.get<{ mode: AuthMode }>("/auth/mode");
  return data.mode;
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
