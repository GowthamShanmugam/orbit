import { getMe } from "@/api/auth";
import { apiClient, getStoredToken, setStoredToken } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
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
      <div className="flex h-screen items-center justify-center bg-[#0d1117]">
        <p className="text-sm text-[#8b949e]">Loading…</p>
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
    <div className="flex h-screen items-center justify-center bg-[#0d1117]">
      <div className="w-full max-w-sm rounded-lg border border-[#30363d] bg-[#161b22] p-6 shadow-lg">
        <div className="mb-6 text-center">
          <h1 className="text-xl font-bold text-[#e6edf3]">Orbit</h1>
          <p className="mt-1 text-xs text-[#8b949e]">
            Context-First AI IDE
          </p>
        </div>

        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-[#8b949e]">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded border border-[#30363d] bg-[#0d1117] px-3 py-2 text-sm text-[#e6edf3] outline-none focus:border-[#58a6ff]"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-[#8b949e]">
              Full Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded border border-[#30363d] bg-[#0d1117] px-3 py-2 text-sm text-[#e6edf3] outline-none focus:border-[#58a6ff]"
            />
          </div>

          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}

          <button
            onClick={handleLogin}
            disabled={loading || !email}
            className="w-full rounded bg-[#238636] px-4 py-2 text-sm font-medium text-white hover:bg-[#2ea043] disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in (dev mode)"}
          </button>
        </div>

        <p className="mt-4 text-center text-[10px] text-[#484f58]">
          Development mode — SSO will be used in production
        </p>
      </div>
    </div>
  );
}
