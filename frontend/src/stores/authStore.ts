import type { AuthMode } from "@/api/auth";
import { setStoredToken } from "@/lib/tokenStorage";
import type { User } from "@/types";
import { create } from "zustand";

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  /** Set on bootstrap from GET /auth/mode — kept across local logout so UI still knows OCP vs dev. */
  authMode: AuthMode | null;
  /** oauth-proxy sign-out path when authMode === "ocp" (optional). */
  ocpSignoutPath: string | null;
  /** Full IdP logout URL when authMode === "ocp" (optional). */
  ocpSignoutUrl: string | null;
  login: (token: string, user: User) => void;
  logout: () => void;
  setAuthContext: (ctx: {
    authMode: AuthMode;
    ocpSignoutPath: string | null;
    ocpSignoutUrl: string | null;
  }) => void;
  setUser: (user: User | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  authMode: null,
  ocpSignoutPath: null,
  ocpSignoutUrl: null,
  login: (token, user) => {
    setStoredToken(token);
    set({ token, user, isAuthenticated: true });
  },
  logout: () => {
    setStoredToken(null);
    set({ token: null, user: null, isAuthenticated: false });
  },
  setAuthContext: ({ authMode, ocpSignoutPath, ocpSignoutUrl }) =>
    set({ authMode, ocpSignoutPath, ocpSignoutUrl }),
  setUser: (user) => set({ user }),
}));
