import { useEditorStore } from "@/stores/editorStore";
import { useThemeStore } from "@/stores/themeStore";
import Editor from "@monaco-editor/react";
import clsx from "clsx";
import { Circle, FileCode, X } from "lucide-react";
import { useMemo } from "react";

export default function EditorPanel() {
  const tabs = useEditorStore((s) => s.tabs);
  const activeTabId = useEditorStore((s) => s.activeTabId);
  const setActiveTab = useEditorStore((s) => s.setActiveTab);
  const closeTab = useEditorStore((s) => s.closeTab);

  const activeTab = useMemo(
    () => tabs.find((t) => t.id === activeTabId),
    [tabs, activeTabId]
  );

  const editorTheme = useThemeStore((s) => s.theme === "dark" ? "vs-dark" : "vs");
  const showWelcome = !activeTab;

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-[var(--o-bg)]">
      <div className="flex h-9 shrink-0 items-end gap-0 overflow-x-auto border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-1 pt-1">
        {tabs.length === 0 && (
          <div className="flex h-8 shrink-0 items-center gap-2 px-3 text-xs font-medium text-[var(--o-text-tertiary)]">
            <FileCode className="h-3.5 w-3.5 shrink-0" />
            <span>No files open</span>
          </div>
        )}
        {tabs.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "group flex h-8 max-w-[220px] shrink-0 items-center rounded-t-md border border-b-0 text-xs font-medium transition-colors",
              activeTabId === t.id
                ? "border-[var(--o-border)] bg-[var(--o-bg)] text-[var(--o-text)]"
                : "border-transparent bg-transparent text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
            )}
          >
            <button
              type="button"
              onClick={() => setActiveTab(t.id)}
              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-0 text-left"
            >
              <span className="truncate">
                {t.path.split("/").pop() || t.path}
              </span>
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(t.id);
              }}
              className="mr-1 flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--o-text-tertiary)] opacity-0 transition-all hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)] group-hover:opacity-100"
              aria-label={`Close ${t.path}`}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>

      <div className="relative min-h-0 flex-1">
        {showWelcome ? (
          <div className="flex h-full flex-col items-center justify-center gap-5 px-8 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--o-accent-muted)]" style={{ boxShadow: "var(--o-shadow-glow)" }}>
              <Circle className="h-8 w-8 text-[var(--o-accent)]" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-[var(--o-text)]">
                Welcome to Orbit
              </h2>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-[var(--o-text-secondary)]">
                Click a file in the Explorer to view it here, or ask the AI
                about your code — file references in chat are clickable.
              </p>
            </div>
          </div>
        ) : (
          <Editor
            height="100%"
            theme={editorTheme}
            path={activeTab.path}
            language={activeTab.language}
            value={activeTab.content}
            options={{
              readOnly: true,
              minimap: { enabled: true },
              fontSize: 13,
              fontFamily:
                "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              scrollBeyondLastLine: false,
              automaticLayout: true,
              padding: { top: 8 },
            }}
          />
        )}
      </div>
    </div>
  );
}
