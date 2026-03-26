import clsx from "clsx";
import {
  ChevronLeft,
  FolderKanban,
  GitBranch,
  KeyRound,
  Package,
  Settings,
} from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";

const nav = [
  { to: "/projects", label: "Projects", icon: FolderKanban, end: true },
  { to: "/hub", label: "Context Hub", icon: Package, end: false },
  { to: "/workflows", label: "Workflows", icon: GitBranch, end: false },
  { to: "/secrets", label: "Secrets", icon: KeyRound, end: false },
  { to: "/settings", label: "Settings", icon: Settings, end: false },
];

interface SidebarProps {
  collapsed: boolean;
  width: number;
  onToggleCollapse: () => void;
  onResizeStart: (e: React.MouseEvent) => void;
}

export default function Sidebar({
  collapsed,
  width,
  onToggleCollapse,
  onResizeStart,
}: SidebarProps) {
  const { pathname } = useLocation();

  return (
    <aside
      className={clsx(
        "relative flex h-full shrink-0 flex-col border-r border-[var(--o-border)] bg-[var(--o-bg-raised)] transition-[width] duration-200 ease-out shadow-[1px_0_0_var(--o-border)]",
        collapsed && "w-14"
      )}
      style={!collapsed ? { width } : undefined}
    >
      <div className="flex h-11 items-center justify-between border-b border-[var(--o-border)] px-2">
        {!collapsed && (
          <span className="px-2 text-[10px] font-semibold uppercase tracking-widest text-[var(--o-text-tertiary)]">
            Workspace
          </span>
        )}
        <button
          type="button"
          onClick={onToggleCollapse}
          className={clsx(
            "o-btn-icon h-7 w-7 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]",
            collapsed && "mx-auto"
          )}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronLeft
            className={clsx(
              "h-3.5 w-3.5 transition-transform",
              collapsed && "rotate-180"
            )}
          />
        </button>
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 p-2">
        {nav.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={label}
            to={to}
            end={end}
            title={collapsed ? label : undefined}
            className={({ isActive }) => {
              const projectsActive =
                label === "Projects" &&
                (pathname === "/projects" || pathname.startsWith("/projects/"));
              const active = label === "Projects" ? projectsActive : isActive;
              return clsx(
                "relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-all duration-150",
                collapsed && "justify-center px-0",
                active
                  ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)] before:absolute before:left-0 before:top-1 before:bottom-1 before:w-[3px] before:rounded-r-full before:bg-[var(--o-accent)]"
                  : "text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
              );
            }}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>
      {!collapsed && (
        <div
          role="separator"
          aria-orientation="vertical"
          onMouseDown={onResizeStart}
          className="absolute right-0 top-0 z-10 h-full w-1 cursor-col-resize transition-colors hover:bg-[var(--o-accent)]/50"
        />
      )}
    </aside>
  );
}
