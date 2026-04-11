import ChatPanel from "@/components/Chat/ChatPanel";
import ContextManager from "@/components/ContextManager/ContextManager";
import EditorPanel from "@/components/Editor/EditorPanel";
import {
  downloadArtifactFile,
  listArtifactDirectory,
  readArtifactFile,
} from "@/api/artifacts";
import {
  listDirectory,
  listRepos,
  readFile,
  type FileEntry,
  type RepoInfo,
} from "@/api/files";
import { getProject } from "@/api/projects";
import { deleteSession, getSession, listMessages } from "@/api/sessions";
import {
  canWriteProject,
  effectiveProjectAccess,
} from "@/lib/projectAccess";
import { recordRecentSession, removeRecentSession } from "@/lib/recentSessions";
import { useEditorStore } from "@/stores/editorStore";
import { useProjectStore } from "@/stores/projectStore";
import { useSessionStore } from "@/stores/sessionStore";
import { useThreadStore } from "@/stores/threadStore";
import clsx from "clsx";
import {
  ChevronDown,
  ChevronRight,
  Download,
  File,
  FileCode2,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  GitBranch,
  Layers,
  Loader2,
  Trash2,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useNavigate, useParams } from "react-router-dom";

// ---------------------------------------------------------------------------
// Panel sizing
// ---------------------------------------------------------------------------

const EXPLORER_MIN = 180;
const EXPLORER_MAX = 400;
const EXPLORER_DEFAULT = 250;

const CHAT_MIN = 280;
const CHAT_MAX = 600;
const CHAT_DEFAULT = 360;

const STORAGE_EXPLORER_WIDTH = "orbit_session_explorer_width";
const STORAGE_CHAT_WIDTH = "orbit_session_chat_width";

/** Virtual repo id for editor tabs — session AI documents are not git repos. */
const ARTIFACT_REPO_ID = "__orbit_session_artifacts__";
const ARTIFACT_REPO_NAME = "Session documents";

function readStoredPanelWidth(
  key: string,
  fallback: number,
  min: number,
  max: number,
): number {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return fallback;
    const n = Number.parseFloat(raw);
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, Math.round(n)));
  } catch {
    return fallback;
  }
}

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
  direction: "left" | "right" = "left",
  storageKey?: string,
) {
  const [width, setWidth] = useState(() =>
    storageKey
      ? readStoredPanelWidth(storageKey, initial, min, max)
      : initial,
  );
  const widthRef = useRef(width);
  widthRef.current = width;

  const dragRef = useRef<{ startX: number; startW: number } | null>(null);
  const resizeActiveRef = useRef(false);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      resizeActiveRef.current = true;
      dragRef.current = { startX: e.clientX, startW: width };
    },
    [width],
  );

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragRef.current) return;
      const delta = e.clientX - dragRef.current.startX;
      const raw =
        direction === "left"
          ? dragRef.current.startW + delta
          : dragRef.current.startW - delta;
      const next = Math.min(max, Math.max(min, raw));
      setWidth(next);
      widthRef.current = next;
    }
    function onUp() {
      if (resizeActiveRef.current) {
        resizeActiveRef.current = false;
        if (storageKey) {
          try {
            localStorage.setItem(
              storageKey,
              String(Math.round(widthRef.current)),
            );
          } catch {
            /* storage full / denied */
          }
        }
      }
      dragRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [min, max, direction, storageKey]);

  return { width, onMouseDown };
}

// ---------------------------------------------------------------------------
// Explorer: Session artifacts + repo file tree
// ---------------------------------------------------------------------------

function SessionArtifactsSection({
  projectId,
  sessionId,
}: {
  projectId: string;
  sessionId: string;
}) {
  const [open, setOpen] = useState(true);

  return (
    <div className="px-1">
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
        <FileText className="h-3 w-3 shrink-0 text-[var(--o-accent)]" />
        <span className="truncate">Session documents</span>
      </button>
      <p className="mb-1 px-2 text-[10px] leading-snug text-[var(--o-text-tertiary)]">
        AI reports and exports for this session. Ask the assistant to save files
        here — they appear below.
      </p>
      {open && (
        <ArtifactDirectoryContents
          projectId={projectId}
          sessionId={sessionId}
          path=""
          depth={1}
        />
      )}
    </div>
  );
}

function ArtifactDirectoryContents({
  projectId,
  sessionId,
  path,
  depth,
}: {
  projectId: string;
  sessionId: string;
  path: string;
  depth: number;
}) {
  const query = useQuery({
    queryKey: ["artifacts", projectId, sessionId, path],
    queryFn: () => listArtifactDirectory(projectId, sessionId, path),
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
        (empty — ask the AI to create a report)
      </div>
    );
  }

  return (
    <div>
      {entries.map((entry) =>
        entry.type === "dir" ? (
          <ArtifactFolderNode
            key={entry.path}
            entry={entry}
            projectId={projectId}
            sessionId={sessionId}
            depth={depth}
          />
        ) : (
          <ArtifactFileNode
            key={entry.path}
            entry={entry}
            projectId={projectId}
            sessionId={sessionId}
            depth={depth}
          />
        ),
      )}
    </div>
  );
}

function ArtifactFolderNode({
  entry,
  projectId,
  sessionId,
  depth,
}: {
  entry: FileEntry;
  projectId: string;
  sessionId: string;
  depth: number;
}) {
  const [folderOpen, setFolderOpen] = useState(false);

  return (
    <div>
      <button
        type="button"
        onClick={() => setFolderOpen((o) => !o)}
        className="flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left text-[12px] text-[var(--o-text)] transition-colors hover:bg-[var(--o-bg-subtle)]"
        style={{ paddingLeft: 4 + depth * 14 }}
      >
        {folderOpen ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
        )}
        {folderOpen ? (
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-[var(--o-warning)]" />
        ) : (
          <Folder className="h-3.5 w-3.5 shrink-0 text-[var(--o-warning)]" />
        )}
        <span className="truncate">{entry.name}</span>
      </button>
      {folderOpen && (
        <ArtifactDirectoryContents
          projectId={projectId}
          sessionId={sessionId}
          path={entry.path}
          depth={depth + 1}
        />
      )}
    </div>
  );
}

function ArtifactFileNode({
  entry,
  projectId,
  sessionId,
  depth,
}: {
  entry: FileEntry;
  projectId: string;
  sessionId: string;
  depth: number;
}) {
  const openFile = useEditorStore((s) => s.openFile);
  const activeTabId = useEditorStore((s) => s.activeTabId);
  const isActive = activeTabId === `${ARTIFACT_REPO_ID}::${entry.path}`;

  const handleOpen = useCallback(async () => {
    try {
      const content = await readArtifactFile(projectId, sessionId, entry.path);
      openFile({
        repoId: ARTIFACT_REPO_ID,
        repoName: ARTIFACT_REPO_NAME,
        path: entry.path,
        language: content.language,
        content: content.content,
        totalLines: content.total_lines,
      });
    } catch {
      openFile({
        repoId: ARTIFACT_REPO_ID,
        repoName: ARTIFACT_REPO_NAME,
        path: entry.path,
        language: "plaintext",
        content: "// Failed to load file",
        totalLines: 1,
      });
    }
  }, [projectId, sessionId, entry.path, openFile]);

  const handleDownload = useCallback(
    (e: { stopPropagation: () => void }) => {
      e.stopPropagation();
      void downloadArtifactFile(projectId, sessionId, entry.path);
    },
    [projectId, sessionId, entry.path],
  );

  const FileIcon = entry.name.endsWith(".json")
    ? FileJson
    : entry.name.match(/\.(md|txt|log)$/)
      ? FileText
      : entry.name.match(/\.(ts|tsx|js|jsx|py|go|rs|java|rb)$/)
        ? FileCode2
        : File;

  return (
    <div
      className={clsx(
        "group flex w-full items-center gap-0.5 rounded px-1.5 py-0.5 text-[12px] transition-colors duration-150",
        isActive
          ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
          : "text-[var(--o-text-secondary)] hover:bg-[var(--o-accent-muted)] hover:text-[var(--o-text)]",
      )}
      style={{ paddingLeft: 4 + depth * 14 + 15 }}
    >
      <button
        type="button"
        onClick={handleOpen}
        className="flex min-w-0 flex-1 items-center gap-1 rounded text-left"
      >
        <FileIcon className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{entry.name}</span>
      </button>
      <button
        type="button"
        title="Download"
        onClick={handleDownload}
        className="shrink-0 rounded p-0.5 text-[var(--o-text-tertiary)] opacity-0 hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-accent)] group-hover:opacity-100"
      >
        <Download className="h-3 w-3" />
      </button>
    </div>
  );
}

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
        "flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left text-[12px] transition-colors duration-150",
        isActive
          ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
          : "text-[var(--o-text-secondary)] hover:bg-[var(--o-accent-muted)] hover:text-[var(--o-text)]"
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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const { setSession, clearSession, addMessage } = useSessionStore();
  const clearTabs = useEditorStore((s) => s.clearTabs);
  const closeThread = useThreadStore((s) => s.closeThread);

  const [sidebarTab, setSidebarTab] = useState<"files" | "context">("files");
  const [deleteSessionOpen, setDeleteSessionOpen] = useState(false);

  const explorer = usePanelResize(
    EXPLORER_DEFAULT,
    EXPLORER_MIN,
    EXPLORER_MAX,
    "left",
    STORAGE_EXPLORER_WIDTH,
  );
  const chat = usePanelResize(
    CHAT_DEFAULT,
    CHAT_MIN,
    CHAT_MAX,
    "right",
    STORAGE_CHAT_WIDTH,
  );

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

  const deleteSessionMut = useMutation({
    mutationFn: () => deleteSession(projectId!, sessionId!),
    onSuccess: () => {
      removeRecentSession(projectId!, sessionId!);
      queryClient.invalidateQueries({ queryKey: ["sessions", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      clearSession();
      clearTabs();
      setDeleteSessionOpen(false);
      navigate(`/projects/${projectId}`);
    },
  });

  useEffect(() => {
    if (projectQuery.data) {
      setCurrentProject(projectQuery.data);
    }
  }, [projectQuery.data, setCurrentProject]);

  const sessionTitleForRecent = sessionQuery.data?.title;
  const projectNameForRecent = projectQuery.data?.name;

  useEffect(() => {
    if (
      !projectId ||
      !sessionId ||
      sessionTitleForRecent == null ||
      projectNameForRecent == null
    ) {
      return;
    }
    recordRecentSession({
      projectId,
      sessionId,
      sessionTitle: sessionTitleForRecent,
      projectName: projectNameForRecent,
    });
  }, [projectId, sessionId, sessionTitleForRecent, projectNameForRecent]);

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
      closeThread();
    },
    [sessionId, clearSession, clearTabs, closeThread]
  );

  const session = sessionQuery.data;
  const project = projectQuery.data;
  const sessionReadOnly =
    project != null && !canWriteProject(effectiveProjectAccess(project));

  if (!projectId || !sessionId) return null;

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
                "o-tab flex-1 text-[11px] font-semibold uppercase tracking-wide",
                sidebarTab === "files" ? "o-tab-active" : "o-tab-inactive"
              )}
            >
              Explorer
            </button>
            <button
              type="button"
              onClick={() => setSidebarTab("context")}
              className={clsx(
                "o-tab flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide",
                sidebarTab === "context" ? "o-tab-active" : "o-tab-inactive"
              )}
            >
              <Layers className="h-3 w-3" />
              Context
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {sidebarTab === "files" ? (
              <div className="flex flex-col gap-2">
                <SessionArtifactsSection
                  projectId={projectId}
                  sessionId={sessionId}
                />
                <div className="border-t border-[var(--o-border)] px-1 pt-1">
                  <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
                    Repositories
                  </div>
                  <RepoFileTree projectId={projectId} />
                </div>
              </div>
            ) : (
              <div className="space-y-3 p-2">
                <ContextManager
                  projectId={projectId}
                  sessionId={sessionId}
                  readOnly={sessionReadOnly}
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
          <ChatPanel
            projectId={projectId}
            sessionId={sessionId}
            orgId={project?.org_id ?? null}
            readOnly={sessionReadOnly}
          />
        </div>
      </div>

      <footer className="flex h-7 shrink-0 items-center justify-between gap-2 border-t border-[var(--o-border)] bg-[var(--o-bg-raised)] px-3 text-[11px] text-[var(--o-text-tertiary)]" style={{ boxShadow: "0 -1px 3px rgba(0,0,0,0.06)" }}>
        <span className="min-w-0 truncate font-medium text-[var(--o-text-secondary)]">
          {session?.title ?? "Session"}
        </span>
        <div className="flex shrink-0 items-center gap-1.5">
          {!sessionReadOnly && (
            <button
              type="button"
              title="Delete session"
              disabled={deleteSessionMut.isPending}
              className="rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-danger)]/10 hover:text-[var(--o-danger)] disabled:opacity-40"
              onClick={() => setDeleteSessionOpen(true)}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
          <span className="hidden sm:inline">{modelLabel}</span>
        </div>
      </footer>

      {deleteSessionOpen && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          role="presentation"
          onClick={() => !deleteSessionMut.isPending && setDeleteSessionOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-session-ide-title"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2
                id="delete-session-ide-title"
                className="text-lg font-semibold text-[var(--o-text)]"
              >
                Delete session?
              </h2>
              <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
                <span className="font-medium text-[var(--o-text)]">
                  {session?.title ?? "This session"}
                </span>{" "}
                and its chat history will be removed. This cannot be undone.
              </p>
            </div>
            {deleteSessionMut.isError && (
              <p className="px-6 pt-4 text-sm text-[var(--o-danger)]">
                {(deleteSessionMut.error as Error)?.message ?? "Delete failed."}
              </p>
            )}
            <div className="flex justify-end gap-2 px-6 py-5">
              <button
                type="button"
                disabled={deleteSessionMut.isPending}
                onClick={() => setDeleteSessionOpen(false)}
                className="o-btn-ghost rounded-lg px-4 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteSessionMut.isPending}
                onClick={() => deleteSessionMut.mutate()}
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--o-danger)]/40 bg-[var(--o-danger)]/10 px-4 py-2 text-sm font-medium text-[var(--o-danger)] hover:bg-[var(--o-danger)]/20 disabled:opacity-50"
              >
                {deleteSessionMut.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                Delete session
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
