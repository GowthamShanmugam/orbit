import { handleSessionExpired } from "@/lib/authSession";
import { getStoredToken } from "@/lib/tokenStorage";
import { useOrbiStore } from "@/stores/orbiStore";
import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

export { getStoredToken, setStoredToken } from "@/lib/tokenStorage";

export const apiClient = axios.create({
  baseURL: "/api",
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

/* ------------------------------------------------------------------
   Orbi reaction: detect button-click-initiated API calls.
   When a user clicks a button/link, we set a short flag. Any
   non-GET API call that starts within that window is considered
   user-initiated → Orbi shows thinking, then happy/error.
   ------------------------------------------------------------------ */

let lastClickMs = 0;
const CLICK_WINDOW_MS = 600;
let pendingUserCalls = 0;

if (typeof document !== "undefined") {
  document.addEventListener(
    "click",
    (e) => {
      const el = e.target as HTMLElement;
      if (el.closest("button, a, [role='button']")) {
        lastClickMs = Date.now();
      }
    },
    { capture: true, passive: true },
  );
}

function isUserInitiated(): boolean {
  return Date.now() - lastClickMs < CLICK_WINDOW_MS;
}

function orbiStartThinking() {
  const s = useOrbiStore.getState();
  if (s.state !== "thinking") s.setState("thinking");
}

function orbiFlashResult(success: boolean) {
  const s = useOrbiStore.getState();
  if (success) s.flashHappy();
  else s.flashError();
}

type TaggedConfig = InternalAxiosRequestConfig & { _orbiTracked?: boolean };

apiClient.interceptors.request.use((config: TaggedConfig) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  const method = (config.method ?? "get").toLowerCase();
  if (method !== "get" && isUserInitiated()) {
    config._orbiTracked = true;
    pendingUserCalls++;
    if (pendingUserCalls === 1) orbiStartThinking();
  }

  return config;
});

apiClient.interceptors.response.use(
  (response) => {
    const cfg = response.config as TaggedConfig;
    if (cfg._orbiTracked) {
      pendingUserCalls = Math.max(0, pendingUserCalls - 1);
      if (pendingUserCalls === 0) {
        const body = response.data;
        const isBodyFailure =
          body && typeof body === "object" && "connected" in body && body.connected === false;
        orbiFlashResult(!isBodyFailure);
      }
    }
    return response;
  },
  (error: AxiosError) => {
    const cfg = (error.config ?? {}) as TaggedConfig;
    if (cfg._orbiTracked) {
      pendingUserCalls = Math.max(0, pendingUserCalls - 1);
      if (pendingUserCalls === 0) orbiFlashResult(false);
    }

    const status = error.response?.status;
    if (status !== 401) {
      return Promise.reject(error);
    }
    const url = cfg.url ?? "";
    const isExternalProxy =
      url.includes("/test-connection") ||
      url.includes("/test") ||
      url.includes("/clusters/");
    if (
      isExternalProxy ||
      url.includes("/auth/mode") ||
      url.includes("/auth/whoami")
    ) {
      return Promise.reject(error);
    }
    handleSessionExpired();
    return Promise.reject(error);
  },
);
