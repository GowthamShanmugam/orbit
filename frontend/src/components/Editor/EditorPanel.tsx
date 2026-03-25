import Editor from "@monaco-editor/react";
import clsx from "clsx";
import { FileCode, X } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

export interface EditorTab {
  id: string;
  path: string;
  language?: string;
  value?: string;
}

const WELCOME_TAB_ID = "__welcome__";

export default function EditorPanel() {
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeId, setActiveId] = useState<string>(WELCOME_TAB_ID);

  const activeTab = useMemo(
    () => tabs.find((t) => t.id === activeId),
    [tabs, activeId]
  );

  const editorLanguage = activeTab?.language ?? "typescript";
  const editorValue =
    activeTab?.value ??
    "// Open a file from the explorer to start editing.\n";

  const handleEditorChange = useCallback(
    (val: string | undefined) => {
      if (!activeTab || activeId === WELCOME_TAB_ID) return;
      setTabs((prev) =>
        prev.map((t) =>
          t.id === activeTab.id ? { ...t, value: val ?? "" } : t
        )
      );
    },
    [activeId, activeTab]
  );

  const openSample = useCallback(() => {
    const id = "sample-readme";
    setTabs((prev) => {
      if (prev.some((t) => t.id === id)) return prev;
      return [
        ...prev,
        {
          id,
          path: "README.md",
          language: "markdown",
          value: "# Orbit\n\nContext-first AI IDE.\n",
        },
      ];
    });
    setActiveId(id);
  }, []);

  const closeTab = useCallback((id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setTabs((prev) => {
      const next = prev.filter((t) => t.id !== id);
      return next;
    });
    setActiveId((cur) => {
      if (cur !== id) return cur;
      return WELCOME_TAB_ID;
    });
  }, []);

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col border-r border-[#30363d] bg-[#0d1117]">
      <div className="flex h-9 shrink-0 items-end gap-0 overflow-x-auto border-b border-[#30363d] bg-[#161b22] px-1 pt-1">
        <button
          type="button"
          onClick={() => setActiveId(WELCOME_TAB_ID)}
          className={clsx(
            "flex h-8 max-w-[200px] shrink-0 items-center gap-2 rounded-t-md border border-b-0 px-3 text-xs font-medium transition-colors",
            activeId === WELCOME_TAB_ID
              ? "border-[#30363d] bg-[#0d1117] text-[#e6edf3]"
              : "border-transparent bg-transparent text-[#8b949e] hover:bg-[#21262d] hover:text-[#e6edf3]"
          )}
        >
          <FileCode className="h-3.5 w-3.5 shrink-0 opacity-70" />
          <span className="truncate">Welcome</span>
        </button>
        {tabs.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "group flex h-8 max-w-[220px] shrink-0 items-center rounded-t-md border border-b-0 text-xs font-medium transition-colors",
              activeId === t.id
                ? "border-[#30363d] bg-[#0d1117] text-[#e6edf3]"
                : "border-transparent bg-transparent text-[#8b949e] hover:bg-[#21262d]"
            )}
          >
            <button
              type="button"
              onClick={() => setActiveId(t.id)}
              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-0 text-left"
            >
              <span className="truncate">{t.path}</span>
            </button>
            <button
              type="button"
              onClick={(e) => closeTab(t.id, e)}
              className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded text-[#8b949e] opacity-0 transition-opacity hover:bg-[#30363d] hover:text-[#e6edf3] group-hover:opacity-100"
              aria-label={`Close ${t.path}`}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
      <div className="relative min-h-0 flex-1">
        {activeId === WELCOME_TAB_ID ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
            <div className="rounded-full border border-[#30363d] bg-[#161b22] p-5">
              <FileCode className="h-10 w-10 text-[#58a6ff]" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-[#e6edf3]">
                Welcome to Orbit
              </h2>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-[#8b949e]">
                Select a file in the explorer or open a sample tab to try the
                editor. Monaco runs with the VS Code dark theme for a familiar
                feel.
              </p>
            </div>
            <button
              type="button"
              onClick={openSample}
              className="rounded-md border border-[#30363d] bg-[#21262d] px-4 py-2 text-sm font-medium text-[#e6edf3] transition-colors hover:border-[#58a6ff]/50"
            >
              Open sample README
            </button>
          </div>
        ) : (
          <Editor
            height="100%"
            theme="vs-dark"
            path={activeTab?.path}
            defaultLanguage={editorLanguage}
            language={editorLanguage}
            value={editorValue}
            onChange={handleEditorChange}
            options={{
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
