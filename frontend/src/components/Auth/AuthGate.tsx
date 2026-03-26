import { getMe } from "@/api/auth";
import { apiClient, getStoredToken, setStoredToken } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
import { Circle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, login, logout } = useAuthStore();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    async function bootstrap() {
      const token = getStoredToken();
      if (!token) {
        setChecking(false);
        return;
      }
      try {
        const user = await getMe();
        login(token, user);
      } catch {
        logout();
      }
      setChecking(false);
    }
    bootstrap();
  }, [login, logout]);

  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center bg-[var(--o-bg)]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--o-accent)]" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <DevLoginScreen />;
  }

  return <>{children}</>;
}

function DevLoginScreen() {
  const { login } = useAuthStore();
  const [email, setEmail] = useState("gshanmug@redhat.com");
  const [name, setName] = useState("Ganesh Shanmugam");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleLogin() {
    setLoading(true);
    setError("");
    try {
      const { data } = await apiClient.post<{ access_token: string }>(
        "/auth/token",
        { email, full_name: name },
      );
      setStoredToken(data.access_token);
      const user = await getMe();
      login(data.access_token, user);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Login failed";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--o-bg)]">
      <div className="w-full max-w-sm" style={{ boxShadow: "var(--o-shadow-xl)" }}>
        <div className="rounded-2xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-8">
          <div className="mb-8 flex flex-col items-center gap-3 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--o-accent)] shadow-lg">
              <Circle className="h-6 w-6 fill-white text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-[var(--o-text)]">Orbit</h1>
              <p className="mt-0.5 text-xs text-[var(--o-text-secondary)]">
                Context-First AI IDE
              </p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="o-input w-full px-3 py-2.5 text-sm"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                Full Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="o-input w-full px-3 py-2.5 text-sm"
              />
            </div>

            {error && (
              <p className="rounded-md bg-[var(--o-danger)]/10 px-3 py-2 text-xs text-[var(--o-danger)]">{error}</p>
            )}

            <button
              onClick={handleLogin}
              disabled={loading || !email}
              className="o-btn-primary flex w-full items-center justify-center gap-2 px-4 py-2.5 text-sm disabled:opacity-50"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </div>

          <p className="mt-6 text-center text-[10px] text-[var(--o-text-tertiary)]">
            Development mode — SSO will be used in production
          </p>
        </div>
      </div>
    </div>
  );
}
