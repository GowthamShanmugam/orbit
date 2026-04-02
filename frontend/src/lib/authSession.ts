import { queryClient } from "@/queryClient";
import { useAuthStore } from "@/stores/authStore";

let redirecting = false;

/** Clear auth, React Query cache, and go to app root so AuthGate shows login / SSO refresh. */
export function handleSessionExpired(): void {
  if (redirecting) return;
  redirecting = true;
  useAuthStore.getState().logout();
  queryClient.clear();
  if (window.location.pathname === "/" || window.location.pathname === "") {
    window.location.reload();
  } else {
    window.location.assign("/");
  }
}
