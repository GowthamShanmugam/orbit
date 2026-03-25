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
        "relative flex h-full shrink-0 flex-col border-r border-[#30363d] bg-[#161b22] transition-[width] duration-200 ease-out",
        collapsed && "w-14"
      )}
      style={!collapsed ? { width } : undefined}
    >
      <div className="flex h-11 items-center justify-between border-b border-[#30363d] px-2">
        {!collapsed && (
          <span className="px-2 text-xs font-semibold uppercase tracking-wider text-[#8b949e]">
            Workspace
          </span>
        )}
        <button
          type="button"
          onClick={onToggleCollapse}
          className={clsx(
            "flex h-8 w-8 items-center justify-center rounded-md text-[#8b949e] transition-colors hover:bg-[#21262d] hover:text-[#e6edf3]",
            collapsed && "mx-auto"
          )}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronLeft
            className={clsx(
              "h-4 w-4 transition-transform",
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
                "flex items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                collapsed && "justify-center px-0",
                active
                  ? "bg-[#21262d] text-[#58a6ff]"
                  : "text-[#8b949e] hover:bg-[#21262d] hover:text-[#e6edf3]"
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
          className="absolute right-0 top-0 z-10 h-full w-1 cursor-col-resize hover:bg-[#58a6ff]/40"
        />
      )}
    </aside>
  );
}
