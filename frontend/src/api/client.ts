import { handleSessionExpired } from "@/lib/authSession";
import { getStoredToken } from "@/lib/tokenStorage";
import axios, { type AxiosError } from "axios";

export { getStoredToken, setStoredToken } from "@/lib/tokenStorage";

export const apiClient = axios.create({
  baseURL: "/api",
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status;
    if (status !== 401) {
      return Promise.reject(error);
    }
    const cfg = error.config as { url?: string } | undefined;
    const url = cfg?.url ?? "";
    // Bootstrap: AuthGate handles failure without a hard redirect
    if (
      url.includes("/auth/mode") ||
      url.includes("/auth/whoami")
    ) {
      return Promise.reject(error);
    }
    handleSessionExpired();
    return Promise.reject(error);
  },
);
