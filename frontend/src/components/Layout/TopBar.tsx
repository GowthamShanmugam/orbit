import { useAuthStore } from "@/stores/authStore";
import { useProjectStore } from "@/stores/projectStore";
import { useSessionStore } from "@/stores/sessionStore";
import { useThemeStore } from "@/stores/themeStore";
import { Circle, LogOut, Moon, Sun, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

const MODEL_LABELS: Record<string, string> = {
  "claude-opus-4-6": "Claude Opus 4.6",
  "claude-sonnet-4-6": "Claude Sonnet 4.6",
  "claude-sonnet-4-5-20250929": "Claude Sonnet 4.5",
  "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
};

export default function TopBar() {
  const { id: projectId, sessionId } = useParams<{
    id?: string;
    sessionId?: string;
  }>();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const currentProject = useProjectStore((s) => s.currentProject);
  const currentSession = useSessionStore((s) => s.currentSession);
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  const modelLabel = currentSession?.model
    ? MODEL_LABELS[currentSession.model] ?? currentSession.model
    : null;

  const projectName = currentProject?.name ?? "Projects";
  const sessionTitle = currentSession?.title;

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-4" style={{ boxShadow: "var(--o-shadow-sm)" }}>
      <div className="flex min-w-0 items-center gap-6">
        <Link
          to="/projects"
          className="flex shrink-0 items-center gap-2.5 text-[var(--o-text)] transition-opacity hover:opacity-80"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--o-accent)] shadow-sm">
            <Circle className="h-3.5 w-3.5 fill-white text-white" />
          </div>
          <span className="text-sm font-bold tracking-tight">ORBIT</span>
        </Link>
        <nav
          className="flex min-w-0 items-center gap-2 text-sm text-[var(--o-text-secondary)]"
          aria-label="Breadcrumb"
        >
          {projectId ? (
            <>
              <Link
                to={`/projects/${projectId}`}
                className="truncate font-medium text-[var(--o-text)] transition-colors hover:text-[var(--o-accent)]"
              >
                {projectName}
              </Link>
              {sessionId && sessionTitle && (
                <>
                  <span className="text-[var(--o-text-tertiary)]">/</span>
                  <span className="truncate text-[var(--o-text-secondary)]">{sessionTitle}</span>
                </>
              )}
            </>
          ) : (
            <span className="text-[var(--o-text-secondary)]">Dashboard</span>
          )}
        </nav>
      </div>
      <div className="flex items-center gap-2">
        {modelLabel && (
          <span className="rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-2.5 py-1 text-[11px] font-medium text-[var(--o-text-secondary)]">
            {modelLabel}
          </span>
        )}
        <button
          type="button"
          onClick={toggleTheme}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--o-text-secondary)] transition-all hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((o) => !o);
            }}
            className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg bg-[var(--o-accent)] text-xs font-semibold text-white transition-all hover:opacity-90"
            aria-label="Account menu"
          >
            {user?.name?.charAt(0)?.toUpperCase() ?? "?"}
          </button>
          {menuOpen && (
            <div className="o-modal absolute right-0 top-full z-50 mt-2 w-48 overflow-hidden py-1">
              <button
                type="button"
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-[var(--o-text)] transition-colors hover:bg-[var(--o-accent-muted)]"
              >
                <User className="h-4 w-4 text-[var(--o-text-secondary)]" />
                Profile
              </button>
              <button
                type="button"
                onClick={() => {
                  logout();
                  setMenuOpen(false);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-[var(--o-danger)] transition-colors hover:bg-[var(--o-danger)]/8"
              >
                <LogOut className="h-4 w-4" />
                Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
