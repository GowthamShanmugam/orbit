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

export async function devToken(): Promise<{ access_token: string }> {
  const { data } = await apiClient.post<{ access_token: string }>(
    "/auth/dev-token",
    {}
  );
  return data;
}
