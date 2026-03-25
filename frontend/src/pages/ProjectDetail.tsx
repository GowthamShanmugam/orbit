import { getProject, updateProject } from "@/api/projects";
import {
  createSession,
  listSessions,
} from "@/api/sessions";
import type { Session } from "@/types";
import { useProjectStore } from "@/stores/projectStore";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Loader2, Pencil, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

const TABS = [
  "Sessions",
  "Context Hub",
  "Workflows",
  "Settings",
] as const;

const SESSION_MODELS = [
  "Claude Sonnet 4",
  "Claude Opus 4",
  "Claude Haiku 3.5",
] as const;

function SessionStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const color =
    s === "active"
      ? "border-[#238636]/50 bg-[#238636]/15 text-[#3fb950]"
      : s === "archived"
        ? "border-[#484f58] bg-[#21262d] text-[#8b949e]"
        : "border-[#d29922]/50 bg-[#d29922]/10 text-[#d29922]";
  return (
    <span
      className={clsx(
        "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        color
      )}
    >
      {status}
    </span>
  );
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Sessions");
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [sessionModal, setSessionModal] = useState(false);
  const [sessionTitle, setSessionTitle] = useState("");
  const [sessionModel, setSessionModel] = useState<string>(SESSION_MODELS[0]);

  const projectQuery = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id!),
    enabled: Boolean(id),
  });

  const sessionsQuery = useQuery({
    queryKey: ["sessions", id],
    queryFn: () => listSessions(id!),
    enabled: Boolean(id),
  });

  useEffect(() => {
    if (projectQuery.data) {
      setCurrentProject(projectQuery.data);
    }
    return () => setCurrentProject(null);
  }, [projectQuery.data, setCurrentProject]);

  useEffect(() => {
    if (editOpen && projectQuery.data) {
      setEditName(projectQuery.data.name);
      setEditDesc(projectQuery.data.description ?? "");
    }
  }, [editOpen, projectQuery.data]);

  const updateMut = useMutation({
    mutationFn: () =>
      updateProject(id!, {
        name: editName.trim(),
        description: editDesc.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", id] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setEditOpen(false);
    },
  });

  const createSessionMut = useMutation({
    mutationFn: () =>
      createSession(id!, {
        title: sessionTitle.trim(),
        model: sessionModel,
      }),
    onSuccess: (session: Session) => {
      queryClient.invalidateQueries({ queryKey: ["sessions", id] });
      setSessionModal(false);
      setSessionTitle("");
      navigate(`/projects/${id}/sessions/${session.id}`);
    },
  });

  const project = projectQuery.data;
  const sessions = sessionsQuery.data ?? [];

  if (projectQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center py-24 text-[#8b949e]">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (projectQuery.isError || !project) {
    return (
      <div className="p-8 text-sm text-[#f85149]">
        Project could not be loaded.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl p-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-[#e6edf3]">
            {project.name}
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#8b949e]">
            {project.description?.trim() || "No description"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditOpen(true)}
          className="inline-flex items-center gap-2 rounded-md border border-[#30363d] bg-[#21262d] px-3 py-2 text-sm font-medium text-[#e6edf3] transition-colors hover:border-[#58a6ff]/40"
        >
          <Pencil className="h-4 w-4 text-[#8b949e]" />
          Edit
        </button>
      </div>

      <div className="mb-6 flex flex-wrap gap-1 border-b border-[#30363d]">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={clsx(
              "relative px-4 py-2.5 text-sm font-medium transition-colors",
              tab === t
                ? "text-[#e6edf3] after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:bg-[#58a6ff]"
                : "text-[#8b949e] hover:text-[#e6edf3]"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Sessions" && (
        <div>
          <div className="mb-4 flex items-center justify-between gap-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[#8b949e]">
              Sessions
            </h2>
            <button
              type="button"
              onClick={() => setSessionModal(true)}
              className="inline-flex items-center gap-2 rounded-md bg-[#21262d] px-3 py-2 text-sm font-medium text-[#e6edf3] ring-1 ring-[#30363d] transition-all hover:ring-[#58a6ff]/40"
            >
              <Plus className="h-4 w-4" />
              New Session
            </button>
          </div>
          {sessionsQuery.isLoading ? (
            <div className="flex justify-center py-12 text-[#8b949e]">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[#30363d] bg-[#161b22]/40 px-6 py-12 text-center text-sm text-[#8b949e]">
              No sessions yet. Start one to open the IDE.
            </div>
          ) : (
            <ul className="divide-y divide-[#30363d] overflow-hidden rounded-lg border border-[#30363d] bg-[#161b22]">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() =>
                      navigate(`/projects/${id}/sessions/${s.id}`)
                    }
                    className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-[#21262d]"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium text-[#e6edf3]">
                        {s.title}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-[#8b949e]">
                        {s.model ?? "Default model"}
                      </p>
                    </div>
                    <SessionStatusBadge status={s.status} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab !== "Sessions" && (
        <div className="rounded-lg border border-dashed border-[#30363d] bg-[#161b22]/30 px-6 py-16 text-center text-sm text-[#8b949e]">
          {tab} will appear here.
        </div>
      )}

      {editOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={() => !updateMut.isPending && setEditOpen(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            className="w-full max-w-md rounded-lg border border-[#30363d] bg-[#161b22] shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[#30363d] px-5 py-4">
              <h2 className="text-lg font-semibold text-[#e6edf3]">
                Edit project
              </h2>
            </div>
            <form
              className="space-y-4 p-5"
              onSubmit={(e) => {
                e.preventDefault();
                if (!editName.trim() || updateMut.isPending) return;
                updateMut.mutate();
              }}
            >
              <div>
                <label
                  htmlFor="edit-name"
                  className="mb-1.5 block text-xs font-medium text-[#8b949e]"
                >
                  Name
                </label>
                <input
                  id="edit-name"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full rounded-md border border-[#30363d] bg-[#0d1117] px-3 py-2 text-sm text-[#e6edf3] outline-none focus:border-[#58a6ff] focus:ring-1 focus:ring-[#58a6ff]"
                />
              </div>
              <div>
                <label
                  htmlFor="edit-desc"
                  className="mb-1.5 block text-xs font-medium text-[#8b949e]"
                >
                  Description
                </label>
                <textarea
                  id="edit-desc"
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  rows={3}
                  className="w-full resize-none rounded-md border border-[#30363d] bg-[#0d1117] px-3 py-2 text-sm text-[#e6edf3] outline-none focus:border-[#58a6ff] focus:ring-1 focus:ring-[#58a6ff]"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={updateMut.isPending}
                  onClick={() => setEditOpen(false)}
                  className="rounded-md px-3 py-2 text-sm text-[#8b949e] hover:bg-[#21262d] hover:text-[#e6edf3]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!editName.trim() || updateMut.isPending}
                  className="inline-flex items-center gap-2 rounded-md bg-[#238636] px-4 py-2 text-sm font-medium text-white hover:bg-[#2ea043] disabled:opacity-50"
                >
                  {updateMut.isPending && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  Save
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {sessionModal && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={() => !createSessionMut.isPending && setSessionModal(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            className="w-full max-w-md rounded-lg border border-[#30363d] bg-[#161b22] shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[#30363d] px-5 py-4">
              <h2 className="text-lg font-semibold text-[#e6edf3]">
                New session
              </h2>
              <p className="mt-1 text-sm text-[#8b949e]">
                Choose a title and a default model for this session.
              </p>
            </div>
            <form
              className="space-y-4 p-5"
              onSubmit={(e) => {
                e.preventDefault();
                if (!sessionTitle.trim() || createSessionMut.isPending) return;
                createSessionMut.mutate();
              }}
            >
              <div>
                <label
                  htmlFor="sess-title"
                  className="mb-1.5 block text-xs font-medium text-[#8b949e]"
                >
                  Title
                </label>
                <input
                  id="sess-title"
                  value={sessionTitle}
                  onChange={(e) => setSessionTitle(e.target.value)}
                  className="w-full rounded-md border border-[#30363d] bg-[#0d1117] px-3 py-2 text-sm text-[#e6edf3] outline-none focus:border-[#58a6ff] focus:ring-1 focus:ring-[#58a6ff]"
                  placeholder="e.g. Refactor auth module"
                  autoFocus
                />
              </div>
              <div>
                <label
                  htmlFor="sess-model"
                  className="mb-1.5 block text-xs font-medium text-[#8b949e]"
                >
                  Model
                </label>
                <select
                  id="sess-model"
                  value={sessionModel}
                  onChange={(e) => setSessionModel(e.target.value)}
                  className="w-full rounded-md border border-[#30363d] bg-[#0d1117] px-3 py-2 text-sm text-[#e6edf3] outline-none focus:border-[#58a6ff] focus:ring-1 focus:ring-[#58a6ff]"
                >
                  {SESSION_MODELS.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={createSessionMut.isPending}
                  onClick={() => setSessionModal(false)}
                  className="rounded-md px-3 py-2 text-sm text-[#8b949e] hover:bg-[#21262d]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!sessionTitle.trim() || createSessionMut.isPending}
                  className="inline-flex items-center gap-2 rounded-md bg-[#238636] px-4 py-2 text-sm font-medium text-white hover:bg-[#2ea043] disabled:opacity-50"
                >
                  {createSessionMut.isPending && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  Open IDE
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
