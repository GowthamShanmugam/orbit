import { useAuthStore } from "@/stores/authStore";
import { useProjectStore } from "@/stores/projectStore";
import { useSessionStore } from "@/stores/sessionStore";
import clsx from "clsx";
import { ChevronDown, Circle, LogOut, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

const MODELS = [
  "Claude Sonnet 4",
  "Claude Opus 4",
  "Claude Haiku 3.5",
] as const;

export default function TopBar() {
  const { id: projectId, sessionId } = useParams<{
    id?: string;
    sessionId?: string;
  }>();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const currentProject = useProjectStore((s) => s.currentProject);
  const currentSession = useSessionStore((s) => s.currentSession);
  const [model, setModel] = useState<string>(MODELS[0]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const modelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) {
        setMenuOpen(false);
      }
      if (!modelRef.current?.contains(e.target as Node)) {
        setModelOpen(false);
      }
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  const projectName = currentProject?.name ?? "Projects";
  const sessionTitle = currentSession?.title;

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-[#30363d] bg-[#161b22] px-4">
      <div className="flex min-w-0 items-center gap-6">
        <Link
          to="/projects"
          className="flex shrink-0 items-center gap-2 text-[#e6edf3] transition-opacity hover:opacity-90"
        >
          <Circle className="h-5 w-5 fill-[#58a6ff] text-[#58a6ff]" />
          <span className="text-sm font-bold tracking-tight">ORBIT</span>
        </Link>
        <nav
          className="flex min-w-0 items-center gap-2 text-sm text-[#8b949e]"
          aria-label="Breadcrumb"
        >
          {projectId ? (
            <>
              <Link
                to={`/projects/${projectId}`}
                className="truncate font-medium text-[#e6edf3] transition-colors hover:text-[#58a6ff]"
              >
                {projectName}
              </Link>
              {sessionId && sessionTitle && (
                <>
                  <span className="text-[#484f58]">/</span>
                  <span className="truncate text-[#e6edf3]">{sessionTitle}</span>
                </>
              )}
            </>
          ) : (
            <span className="text-[#8b949e]">Dashboard</span>
          )}
        </nav>
      </div>
      <div className="flex items-center gap-3">
        <div className="relative" ref={modelRef}>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setModelOpen((o) => !o);
            }}
            className="flex h-9 max-w-[200px] items-center gap-2 rounded-md border border-[#30363d] bg-[#0d1117] px-3 text-left text-xs text-[#e6edf3] transition-colors hover:border-[#484f58]"
          >
            <span className="truncate">{model}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#8b949e]" />
          </button>
          {modelOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-56 overflow-hidden rounded-md border border-[#30363d] bg-[#1c2128] py-1 shadow-xl">
              {MODELS.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => {
                    setModel(m);
                    setModelOpen(false);
                  }}
                  className={clsx(
                    "flex w-full px-3 py-2 text-left text-xs transition-colors hover:bg-[#21262d]",
                    m === model ? "text-[#58a6ff]" : "text-[#e6edf3]"
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((o) => !o);
            }}
            className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-full border border-[#30363d] bg-[#21262d] text-xs font-semibold text-[#e6edf3] transition-colors hover:border-[#58a6ff]/50"
            aria-label="Account menu"
          >
            {user?.name?.charAt(0)?.toUpperCase() ?? "?"}
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full z-50 mt-1 w-48 overflow-hidden rounded-md border border-[#30363d] bg-[#1c2128] py-1 shadow-xl">
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[#e6edf3] transition-colors hover:bg-[#21262d]"
              >
                <User className="h-4 w-4 text-[#8b949e]" />
                Profile
              </button>
              <button
                type="button"
                onClick={() => {
                  logout();
                  setMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[#f85149] transition-colors hover:bg-[#21262d]"
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
