import ChatPanel from "@/components/Chat/ChatPanel";
import EditorPanel from "@/components/Editor/EditorPanel";
import { getProject } from "@/api/projects";
import { getSession, listMessages } from "@/api/sessions";
import { useProjectStore } from "@/stores/projectStore";
import {
  useSessionStore,
} from "@/stores/sessionStore";
import clsx from "clsx";
import {
  ChevronDown,
  ChevronRight,
  File,
  FileJson,
  Folder,
  FolderOpen,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

interface TreeNode {
  name: string;
  type: "file" | "folder";
  children?: TreeNode[];
}

const SAMPLE_TREE: TreeNode[] = [
  {
    name: "orbit",
    type: "folder",
    children: [
      {
        name: "frontend",
        type: "folder",
        children: [
          { name: "package.json", type: "file" },
          { name: "vite.config.ts", type: "file" },
          {
            name: "src",
            type: "folder",
            children: [
              { name: "App.tsx", type: "file" },
              { name: "main.tsx", type: "file" },
            ],
          },
        ],
      },
      { name: "README.md", type: "file" },
    ],
  },
];

function TreeItem({
  node,
  depth,
}: {
  node: TreeNode;
  depth: number;
}) {
  const [open, setOpen] = useState(depth < 2);
  const isFolder = node.type === "folder";
  return (
    <div>
      <button
        type="button"
        onClick={() => isFolder && setOpen((o) => !o)}
        className={clsx(
          "flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left text-[12px] transition-colors",
          isFolder
            ? "text-[#e6edf3] hover:bg-[#21262d]"
            : "text-[#8b949e] hover:bg-[#21262d] hover:text-[#e6edf3]"
        )}
        style={{ paddingLeft: 6 + depth * 12 }}
      >
        {isFolder ? (
          open ? (
            <ChevronDown className="h-3 w-3 shrink-0 text-[#8b949e]" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0 text-[#8b949e]" />
          )
        ) : (
          <span className="inline-block w-3 shrink-0" />
        )}
        {isFolder ? (
          open ? (
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-[#d29922]" />
          ) : (
            <Folder className="h-3.5 w-3.5 shrink-0 text-[#d29922]" />
          )
        ) : node.name.endsWith(".json") ? (
          <FileJson className="h-3.5 w-3.5 shrink-0 text-[#58a6ff]" />
        ) : (
          <File className="h-3.5 w-3.5 shrink-0 text-[#8b949e]" />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isFolder && open && node.children && (
        <div>
          {node.children.map((c) => (
            <TreeItem key={c.name} node={c} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function SessionView() {
  const { id: projectId, sessionId } = useParams<{
    id: string;
    sessionId: string;
  }>();
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const {
    setSession,
    clearSession,
    addMessage,
  } = useSessionStore();

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
    },
    [sessionId, clearSession]
  );

  const session = sessionQuery.data;

  if (!projectId || !sessionId) {
    return null;
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col bg-[#0d1117]">
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[250px] shrink-0 flex-col border-r border-[#30363d] bg-[#161b22]">
          <div className="flex h-9 items-center border-b border-[#30363d] px-3 text-[11px] font-semibold uppercase tracking-wide text-[#8b949e]">
            Explorer
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto py-2">
            {SAMPLE_TREE.map((n) => (
              <TreeItem key={n.name} node={n} depth={0} />
            ))}
          </div>
        </aside>
        <EditorPanel />
        <ChatPanel projectId={projectId} sessionId={sessionId} />
      </div>
      <footer className="flex h-7 shrink-0 items-center justify-between border-t border-[#30363d] bg-[#161b22] px-3 text-[11px] text-[#8b949e]">
        <span className="truncate font-medium text-[#e6edf3]">
          {session?.title ?? "Session"}
        </span>
        <span className="hidden sm:inline">
          {session?.model ?? "Claude Sonnet 4"}
        </span>
        <span className="font-mono tabular-nums text-[#6e7681]">
          ~12.4k tokens
        </span>
      </footer>
    </div>
  );
}
