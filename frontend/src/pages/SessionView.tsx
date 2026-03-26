import ChatPanel from "@/components/Chat/ChatPanel";
import ContextManager from "@/components/ContextManager/ContextManager";
import EditorPanel from "@/components/Editor/EditorPanel";
import {
  listDirectory,
  listRepos,
  readFile,
  type FileEntry,
  type RepoInfo,
} from "@/api/files";
import { getProject } from "@/api/projects";
import { getSession, listMessages } from "@/api/sessions";
import { useEditorStore } from "@/stores/editorStore";
import { useProjectStore } from "@/stores/projectStore";
import { useSessionStore } from "@/stores/sessionStore";
import clsx from "clsx";
import {
  ChevronDown,
  ChevronRight,
  File,
  FileCode2,
  FileJson,
  Folder,
  FolderOpen,
  GitBranch,
  Layers,
  Loader2,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useParams } from "react-router-dom";

// ---------------------------------------------------------------------------
// Panel sizing
// ---------------------------------------------------------------------------

const EXPLORER_MIN = 180;
const EXPLORER_MAX = 400;
const EXPLORER_DEFAULT = 250;

const CHAT_MIN = 280;
const CHAT_MAX = 600;
const CHAT_DEFAULT = 360;

// ---------------------------------------------------------------------------
// Model labels
// ---------------------------------------------------------------------------

const MODEL_LABELS: Record<string, string> = {
  "claude-opus-4-6": "Claude Opus 4.6",
  "claude-sonnet-4-6": "Claude Sonnet 4.6",
  "claude-sonnet-4-5-20250929": "Claude Sonnet 4.5",
  "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
};

// ---------------------------------------------------------------------------
// Drag-resize hook
// ---------------------------------------------------------------------------

function usePanelResize(
  initial: number,
  min: number,
  max: number,
  direction: "left" | "right" = "left"
) {
  const [width, setWidth] = useState(initial);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragRef.current = { startX: e.clientX, startW: width };
    },
    [width]
  );

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragRef.current) return;
      const delta = e.clientX - dragRef.current.startX;
      const raw =
        direction === "left"
          ? dragRef.current.startW + delta
          : dragRef.current.startW - delta;
      setWidth(Math.min(max, Math.max(min, raw)));
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
  }, [min, max, direction]);

  return { width, onMouseDown };
}

// ---------------------------------------------------------------------------
// Explorer: Repo selector + file tree
// ---------------------------------------------------------------------------

function RepoFileTree({ projectId }: { projectId: string }) {
  const reposQuery = useQuery({
    queryKey: ["repos", projectId],
    queryFn: () => listRepos(projectId),
    enabled: Boolean(projectId),
  });

  const repos: RepoInfo[] = reposQuery.data ?? [];
  const clonedRepos = repos.filter((r) => r.cloned);

  if (reposQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 p-3 text-xs text-[var(--o-text-secondary)]">
        <Loader2 className="h-3 w-3 animate-spin" /> Loading repos…
      </div>
    );
  }

  if (clonedRepos.length === 0) {
    return (
      <div className="p-3 text-xs text-[var(--o-border-subtle)]">
        No repositories cloned yet. Add a Context Pack with code repos.
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {clonedRepos.map((repo) => (
        <RepoTree key={repo.id} repo={repo} projectId={projectId} />
      ))}
    </div>
  );
}

function RepoTree({ repo, projectId }: { repo: RepoInfo; projectId: string }) {
  const [open, setOpen] = useState(true);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-[12px] font-semibold text-[var(--o-text)] transition-colors hover:bg-[var(--o-bg-subtle)]"
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
        )}
        <GitBranch className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
        <span className="truncate">{repo.name}</span>
      </button>
      {open && (
        <DirectoryContents
          projectId={projectId}
          repoId={repo.id}
          repoName={repo.name}
          path=""
          depth={1}
        />
      )}
    </div>
  );
}

function DirectoryContents({
  projectId,
  repoId,
  repoName,
  path,
  depth,
}: {
  projectId: string;
  repoId: string;
  repoName: string;
  path: string;
  depth: number;
}) {
  const query = useQuery({
    queryKey: ["dir", projectId, repoId, path],
    queryFn: () => listDirectory(projectId, repoId, path),
  });

  if (query.isLoading) {
    return (
      <div
        className="flex items-center gap-1 py-0.5 text-[11px] text-[var(--o-border-subtle)]"
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <Loader2 className="h-3 w-3 animate-spin" /> loading…
      </div>
    );
  }

  const entries: FileEntry[] = query.data ?? [];
  if (entries.length === 0) {
    return (
      <div
        className="py-0.5 text-[11px] italic text-[var(--o-border-subtle)]"
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        (empty)
      </div>
    );
  }

  return (
    <div>
      {entries.map((entry) =>
        entry.type === "dir" ? (
          <FolderNode
            key={entry.path}
            entry={entry}
            projectId={projectId}
            repoId={repoId}
            repoName={repoName}
            depth={depth}
          />
        ) : (
          <FileNode
            key={entry.path}
            entry={entry}
            projectId={projectId}
            repoId={repoId}
            repoName={repoName}
            depth={depth}
          />
        )
      )}
    </div>
  );
}

function FolderNode({
  entry,
  projectId,
  repoId,
  repoName,
  depth,
}: {
  entry: FileEntry;
  projectId: string;
  repoId: string;
  repoName: string;
  depth: number;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left text-[12px] text-[var(--o-text)] transition-colors hover:bg-[var(--o-bg-subtle)]"
        style={{ paddingLeft: 4 + depth * 14 }}
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
        )}
        {open ? (
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-[var(--o-warning)]" />
        ) : (
          <Folder className="h-3.5 w-3.5 shrink-0 text-[var(--o-warning)]" />
        )}
        <span className="truncate">{entry.name}</span>
      </button>
      {open && (
        <DirectoryContents
          projectId={projectId}
          repoId={repoId}
          repoName={repoName}
          path={entry.path}
          depth={depth + 1}
        />
      )}
    </div>
  );
}

function FileNode({
  entry,
  projectId,
  repoId,
  repoName,
  depth,
}: {
  entry: FileEntry;
  projectId: string;
  repoId: string;
  repoName: string;
  depth: number;
}) {
  const openFile = useEditorStore((s) => s.openFile);
  const activeTabId = useEditorStore((s) => s.activeTabId);
  const isActive = activeTabId === `${repoId}::${entry.path}`;

  const handleClick = useCallback(async () => {
    try {
      const content = await readFile(projectId, repoId, entry.path);
      openFile({
        repoId,
        repoName,
        path: entry.path,
        language: content.language,
        content: content.content,
        totalLines: content.total_lines,
      });
    } catch {
      openFile({
        repoId,
        repoName,
        path: entry.path,
        language: "plaintext",
        content: "// Failed to load file",
        totalLines: 1,
      });
    }
  }, [projectId, repoId, repoName, entry.path, openFile]);

  const FileIcon = entry.name.endsWith(".json")
    ? FileJson
    : entry.name.match(/\.(ts|tsx|js|jsx|py|go|rs|java|rb)$/)
      ? FileCode2
      : File;

  return (
    <button
      type="button"
      onClick={handleClick}
      className={clsx(
        "flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left text-[12px] transition-colors",
        isActive
          ? "bg-[var(--o-accent-bg)]/20 text-[var(--o-accent)]"
          : "text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
      )}
      style={{ paddingLeft: 4 + depth * 14 + 15 }}
    >
      <FileIcon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{entry.name}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Resize handle
// ---------------------------------------------------------------------------

function ResizeHandle({ onMouseDown }: { onMouseDown: (e: React.MouseEvent) => void }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="group relative z-10 flex w-[5px] shrink-0 cursor-col-resize items-center justify-center"
    >
      <div className="h-full w-px bg-[var(--o-border)] transition-colors group-hover:w-[3px] group-hover:bg-[var(--o-accent)]" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// SessionView
// ---------------------------------------------------------------------------

export default function SessionView() {
  const { id: projectId, sessionId } = useParams<{
    id: string;
    sessionId: string;
  }>();
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const { setSession, clearSession, addMessage } = useSessionStore();
  const clearTabs = useEditorStore((s) => s.clearTabs);

  const explorer = usePanelResize(EXPLORER_DEFAULT, EXPLORER_MIN, EXPLORER_MAX, "left");
  const chat = usePanelResize(CHAT_DEFAULT, CHAT_MIN, CHAT_MAX, "right");

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId!),
    enabled: Boolean(projectId),
  });

  const sessionQuery = useQuery({
    queryKey: ["session", projectId, sessionId],
    queryFn: () => getSession(projectId!, sessionId!),
    enabled: Boolean(projectId && sessionId),
  });

  const messagesQuery = useQuery({
    queryKey: ["messages", projectId, sessionId],
    queryFn: () => listMessages(projectId!, sessionId!),
    enabled: Boolean(projectId && sessionId),
  });

  useEffect(() => {
    if (projectQuery.data) {
      setCurrentProject(projectQuery.data);
    }
  }, [projectQuery.data, setCurrentProject]);

  useEffect(() => {
    const session = sessionQuery.data;
    if (!session) return;
    if (messagesQuery.isLoading) {
      clearSession();
      setSession(session);
      return;
    }
    const items = messagesQuery.data ?? [];
    clearSession();
    setSession(session);
    items.forEach((m) => addMessage(m));
  }, [
    sessionId,
    sessionQuery.data,
    messagesQuery.isLoading,
    messagesQuery.dataUpdatedAt,
    clearSession,
    setSession,
    addMessage,
  ]);

  useEffect(
    () => () => {
      clearSession();
      clearTabs();
    },
    [sessionId, clearSession, clearTabs]
  );

  const session = sessionQuery.data;

  if (!projectId || !sessionId) return null;

  const [sidebarTab, setSidebarTab] = useState<"files" | "context">("files");

  const modelLabel = session?.model
    ? MODEL_LABELS[session.model] ?? session.model
    : "Claude Sonnet 4.5";

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col bg-[var(--o-bg)]">
      <div className="flex min-h-0 flex-1">
        {/* Explorer */}
        <aside
          className="flex shrink-0 flex-col border-r border-[var(--o-border)] bg-[var(--o-bg-raised)]"
          style={{ width: explorer.width }}
        >
          <div className="flex h-9 items-center border-b border-[var(--o-border)]">
            <button
              type="button"
              onClick={() => setSidebarTab("files")}
              className={clsx(
                "flex-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide transition-colors",
                sidebarTab === "files"
                  ? "text-[var(--o-text)]"
                  : "text-[var(--o-border-subtle)] hover:text-[var(--o-text-secondary)]"
              )}
            >
              Explorer
            </button>
            <button
              type="button"
              onClick={() => setSidebarTab("context")}
              className={clsx(
                "flex items-center gap-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide transition-colors",
                sidebarTab === "context"
                  ? "text-[var(--o-text)]"
                  : "text-[var(--o-border-subtle)] hover:text-[var(--o-text-secondary)]"
              )}
            >
              <Layers className="h-3 w-3" />
              Context
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {sidebarTab === "files" ? (
              <RepoFileTree projectId={projectId} />
            ) : (
              <div className="space-y-3 p-2">
                <ContextManager
                  projectId={projectId}
                  sessionId={sessionId}
                />
              </div>
            )}
          </div>
        </aside>

        <ResizeHandle onMouseDown={explorer.onMouseDown} />

        {/* Editor (fills remaining space) */}
        <EditorPanel />

        <ResizeHandle onMouseDown={chat.onMouseDown} />

        {/* Chat */}
        <div
          className="flex shrink-0 flex-col border-l border-[var(--o-border)]"
          style={{ width: chat.width }}
        >
          <ChatPanel projectId={projectId} sessionId={sessionId} />
        </div>
      </div>

      <footer className="flex h-7 shrink-0 items-center justify-between border-t border-[var(--o-border)] bg-[var(--o-bg-raised)] px-3 text-[11px] text-[var(--o-text-tertiary)]">
        <span className="truncate font-medium text-[var(--o-text-secondary)]">
          {session?.title ?? "Session"}
        </span>
        <span className="hidden sm:inline">{modelLabel}</span>
      </footer>
    </div>
  );
}
