import clsx from "clsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useMatch } from "react-router-dom";
import ProductTour from "@/components/Onboarding/ProductTour";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 400;
const SIDEBAR_DEFAULT = 250;

export default function MainLayout() {
  const sessionMatch = useMatch("/projects/:id/sessions/:sessionId");
  const isSessionIde = Boolean(sessionMatch);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const onResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startW: sidebarWidth };
    },
    [sidebarWidth]
  );

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragRef.current) return;
      const delta = e.clientX - dragRef.current.startX;
      const next = Math.min(
        SIDEBAR_MAX,
        Math.max(SIDEBAR_MIN, dragRef.current.startW + delta)
      );
      setSidebarWidth(next);
    }
    function onUp() {
      dragRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--o-bg)] text-[var(--o-text)]">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        {!isSessionIde && (
          <Sidebar
            collapsed={sidebarCollapsed}
            width={sidebarWidth}
            onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
            onResizeStart={onResizeStart}
          />
        )}
        <main
          className={clsx(
            "min-h-0 min-w-0 flex-1 overflow-auto",
            isSessionIde && "flex flex-col"
          )}
        >
          <Outlet />
        </main>
      </div>
      {!isSessionIde && <ProductTour />}
    </div>
  );
}
