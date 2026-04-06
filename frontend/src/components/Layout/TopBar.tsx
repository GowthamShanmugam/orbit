import { useAuthStore } from "@/stores/authStore";
import { useProjectStore } from "@/stores/projectStore";
import { useSessionStore } from "@/stores/sessionStore";
import { useThemeStore } from "@/stores/themeStore";
import { ORBIT_REPO_URL, ORBIT_UI_VERSION } from "@/lib/orbitMeta";
import Orbi from "@/components/Orbi/Orbi";
import { Circle, ExternalLink, Info, LogOut, Moon, Sun, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

const MODEL_LABELS: Record<string, string> = {
  "claude-opus-4-6": "Claude Opus 4.6",
  "claude-sonnet-4-6": "Claude Sonnet 4.6",
  "claude-sonnet-4-5-20250929": "Claude Sonnet 4.5",
  "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
};

export default function TopBar() {
  const navigate = useNavigate();
  const { id: projectId, sessionId } = useParams<{
    id?: string;
    sessionId?: string;
  }>();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const authMode = useAuthStore((s) => s.authMode);
  const ocpSignoutPath = useAuthStore((s) => s.ocpSignoutPath);
  const ocpSignoutUrl = useAuthStore((s) => s.ocpSignoutUrl);
  const currentProject = useProjectStore((s) => s.currentProject);
  const currentSession = useSessionStore((s) => s.currentSession);
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const [menuOpen, setMenuOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
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

  const fullName = user?.full_name?.trim() ?? "";
  const emailLocal =
    user?.email?.includes("@") === true
      ? (user.email.split("@")[0]?.trim() ?? "")
      : (user?.email?.trim() ?? "");
  const accountPopoverTitle = fullName || emailLocal || "Signed in";

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-4" style={{ boxShadow: "var(--o-shadow-sm)" }}>
      <div className="flex min-w-0 items-center gap-6">
        <Link
          to="/projects"
          className="flex shrink-0 items-center gap-2.5 text-[var(--o-text)] transition-opacity hover:opacity-80"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#195ad2] shadow-sm">
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
        <Orbi />
        {modelLabel && (
          <span className="o-badge">
            {modelLabel}
          </span>
        )}
        <button
          type="button"
          onClick={() => setAboutOpen(true)}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          aria-label="About Orbit"
        >
          <Info className="h-3.5 w-3.5 shrink-0" />
          <span className="hidden sm:inline">About</span>
        </button>
        <button
          type="button"
          onClick={toggleTheme}
          className="o-btn-icon h-8 w-8 text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
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
            className="o-btn-icon h-8 w-8 text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
            aria-label="Account menu"
          >
            <User className="h-4 w-4" />
          </button>
          {menuOpen && (
            <div className="o-dropdown absolute right-0 top-full z-50 mt-2 w-56 py-1">
              <div className="border-b border-[var(--o-border)] px-3 py-2.5">
                <p
                  className="truncate text-sm font-medium text-[var(--o-text)]"
                  title={accountPopoverTitle}
                >
                  {accountPopoverTitle}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  if (authMode === "ocp") {
                    logout();
                    if (ocpSignoutUrl) {
                      window.location.assign(ocpSignoutUrl);
                      return;
                    }
                    if (ocpSignoutPath) {
                      const rd = encodeURIComponent(
                        `${window.location.origin}/projects`,
                      );
                      window.location.assign(
                        `${window.location.origin}${ocpSignoutPath}?rd=${rd}`,
                      );
                      return;
                    }
                  }
                  logout();
                  navigate("/", { replace: true });
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

      {aboutOpen && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[200] flex items-center justify-center p-4"
          role="presentation"
          onClick={() => setAboutOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="about-orbit-title"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2 id="about-orbit-title" className="text-lg font-semibold text-[var(--o-text)]">
                About Orbit
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-[var(--o-text-secondary)]">
                Context-first AI IDE — project knowledge, workflows, and tools
                stay grounded in your repository and team conventions.
              </p>
            </div>
            <div className="space-y-3 px-6 py-5 text-sm text-[var(--o-text-secondary)]">
              <div className="flex justify-between gap-4">
                <span className="text-[var(--o-text-tertiary)]">UI version</span>
                <span className="font-mono text-[var(--o-text)]">{ORBIT_UI_VERSION}</span>
              </div>
              <a
                href={ORBIT_REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 break-all text-[var(--o-accent)] transition-colors hover:text-[var(--o-accent-hover)]"
              >
                <ExternalLink className="h-4 w-4 shrink-0" />
                {ORBIT_REPO_URL.replace(/^https:\/\//, "")}
              </a>
            </div>
            <div className="flex justify-end border-t border-[var(--o-border)] px-6 py-4">
              <button
                type="button"
                onClick={() => setAboutOpen(false)}
                className="o-btn-ghost rounded-lg px-4 py-2 text-sm"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
