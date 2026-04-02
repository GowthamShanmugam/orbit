import { listInstalledPacks, uninstallPack } from "@/api/contextHub";
import { deleteProject, getProject, updateProject } from "@/api/projects";
import {
  createSession,
  deleteSession,
  listSessions,
} from "@/api/sessions";
import ProjectWorkspaceBadge from "@/components/ProjectWorkspaceBadge";
import ClusterManager from "@/components/Clusters/ClusterManager";
import ContextManager from "@/components/ContextManager/ContextManager";
import ProjectRuntimeSettingsPanel from "@/components/ProjectRuntimeSettingsPanel";
import ProjectSharing from "@/components/ProjectSharing/ProjectSharing";
import VaultManager from "@/components/SecretVault/VaultManager";
import {
  canAdminProject,
  canWriteProject,
  effectiveProjectAccess,
} from "@/lib/projectAccess";
import {
  removeRecentSession,
  removeRecentSessionsForProject,
} from "@/lib/recentSessions";
import type { InstalledPack, Session } from "@/types";
import { useProjectStore } from "@/stores/projectStore";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  FolderKanban,
  Globe,
  Loader2,
  Package,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

const TABS = [
  "Sessions",
  "Context Hub",
  "Clusters",
  "Secrets",
  "Sharing",
  "Settings",
] as const;

function formatProjectUpdated(iso: string) {
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
      new Date(iso),
    );
  } catch {
    return iso;
  }
}

const SESSION_MODELS = [
  { id: "claude-opus-4-6", label: "Claude Opus 4.6" },
  { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
  { id: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
] as const;

function SessionStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const badgeCls =
    s === "active"
      ? "o-badge-green"
      : s === "archived"
        ? "o-badge"
        : "o-badge-warning";
  return (
    <span className={clsx("o-badge", badgeCls)}>
      {status}
    </span>
  );
}

/** Remount when `:id` changes so tab/state does not leak between projects. */
export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  return <ProjectDetailView key={id ?? ""} />;
}

function ProjectDetailView() {
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
  const [sessionModel, setSessionModel] = useState<string>(SESSION_MODELS[0].id);
  const [deleteProjectOpen, setDeleteProjectOpen] = useState(false);
  const [sessionToDelete, setSessionToDelete] = useState<Session | null>(null);

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
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setSessionModal(false);
      setSessionTitle("");
      navigate(`/projects/${id}/sessions/${session.id}`);
    },
  });

  const deleteProjectMut = useMutation({
    mutationFn: () => deleteProject(id!),
    onSuccess: () => {
      removeRecentSessionsForProject(id!);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setCurrentProject(null);
      setDeleteProjectOpen(false);
      navigate("/projects");
    },
  });

  const deleteSessionMut = useMutation({
    mutationFn: (sessionId: string) => deleteSession(id!, sessionId),
    onSuccess: (_void, deletedSessionId) => {
      removeRecentSession(id!, deletedSessionId);
      queryClient.invalidateQueries({ queryKey: ["sessions", id] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setSessionToDelete(null);
    },
  });

  const project = projectQuery.data;
  const sessions = sessionsQuery.data ?? [];
  const projectAccess = effectiveProjectAccess(project);
  const canWrite = canWriteProject(projectAccess);
  const canAdmin = canAdminProject(projectAccess);

  const isPublicProject = project?.visibility === "public";
  const detailTabs = isPublicProject
    ? TABS.filter((t) => t !== "Sharing")
    : [...TABS];

  useEffect(() => {
    if (isPublicProject && tab === "Sharing") {
      setTab("Sessions");
    }
  }, [isPublicProject, tab]);

  if (projectQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center py-24 text-[var(--o-text-secondary)]">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (projectQuery.isError || !project) {
    return (
      <div className="p-8 text-sm text-[var(--o-danger)]">
        Project could not be loaded.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl p-8">
      <header
        className="mb-8 rounded-2xl bg-[var(--o-bg-raised)] p-6 sm:p-7"
        style={{
          backgroundImage: "var(--o-gradient-card)",
          boxShadow: "var(--o-shadow-sm)",
        }}
      >
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="flex min-w-0 flex-1 gap-4 sm:gap-5">
            <div
              className={clsx(
                "flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl shadow-sm",
                isPublicProject
                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                  : "bg-[var(--o-accent-muted)] text-[var(--o-accent)]",
              )}
            >
              {isPublicProject ? (
                <Globe className="h-7 w-7" strokeWidth={1.75} />
              ) : (
                <FolderKanban className="h-7 w-7" strokeWidth={1.75} />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-semibold tracking-tight text-[var(--o-text)] sm:text-[1.75rem]">
                {project.name}
              </h1>
              <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1.5">
                <ProjectWorkspaceBadge project={project} compact />
                {project.shared_with_me && (
                  <>
                    <span
                      className="hidden text-[var(--o-text-tertiary)] sm:inline"
                      aria-hidden
                    >
                      ·
                    </span>
                    <span className="text-sm text-[var(--o-text-secondary)]">
                      Shared by{" "}
                      <span className="font-medium text-[var(--o-text)]">
                        {project.created_by_display?.trim() || "Teammate"}
                      </span>
                    </span>
                  </>
                )}
              </div>
              {project.description?.trim() ? (
                <p className="mt-4 max-w-2xl text-sm leading-relaxed text-[var(--o-text-secondary)]">
                  {project.description.trim()}
                </p>
              ) : (
                <p className="mt-4 max-w-2xl text-sm leading-relaxed text-[var(--o-text-tertiary)]">
                  {canWrite ? (
                    <>
                      <span className="italic">No description yet.</span>{" "}
                      <span className="text-[var(--o-text-secondary)]">
                        Add one from Edit.
                      </span>
                    </>
                  ) : (
                    <span className="italic">No description.</span>
                  )}
                </p>
              )}
              {isPublicProject && (
                <p className="mt-3 max-w-2xl text-xs leading-relaxed text-[var(--o-text-tertiary)]">
                  Everyone signed in can view this project. Only the owner can
                  edit.
                </p>
              )}
              <p className="mt-3 text-xs text-[var(--o-text-tertiary)]">
                Updated {formatProjectUpdated(project.updated_at)}
              </p>
            </div>
          </div>
          <div className="flex w-full shrink-0 flex-wrap gap-2 sm:w-auto sm:justify-end">
            {canWrite && (
              <button
                type="button"
                onClick={() => setEditOpen(true)}
                className="o-btn-ghost inline-flex items-center gap-2 rounded-xl bg-[var(--o-bg-subtle)] px-3 py-2 text-sm transition-colors hover:bg-[var(--o-accent-muted)]"
              >
                <Pencil className="h-3.5 w-3.5" />
                Edit
              </button>
            )}
            {canAdmin && (
              <button
                type="button"
                onClick={() => setDeleteProjectOpen(true)}
                className="inline-flex items-center gap-2 rounded-xl bg-[var(--o-danger)]/10 px-3 py-2 text-sm text-[var(--o-danger)] transition-colors hover:bg-[var(--o-danger)]/18"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete project
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="mb-6 flex flex-wrap gap-0.5 border-b border-[var(--o-border)]">
        {detailTabs.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={clsx(
              "o-tab text-sm",
              tab === t ? "o-tab-active" : "o-tab-inactive"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Sessions" && (
        <div>
          <div className="mb-4 flex items-center justify-between gap-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
              Sessions
            </h2>
            {canWrite && (
              <button
                type="button"
                onClick={() => setSessionModal(true)}
                className="o-btn-ghost inline-flex items-center gap-2 border border-[var(--o-border)] px-3 py-2 text-sm hover:border-[var(--o-accent)]/40 hover:shadow-sm"
              >
                <Plus className="h-4 w-4" />
                New Session
              </button>
            )}
          </div>
          {sessionsQuery.isLoading ? (
            <div className="flex justify-center py-12 text-[var(--o-text-secondary)]">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="o-empty text-sm text-[var(--o-text-secondary)]">
              No sessions yet. Start one to open the IDE.
            </div>
          ) : (
            <ul className="o-list divide-y divide-[var(--o-border)]">
              {sessions.map((s) => (
                <li key={s.id} className="flex items-stretch">
                  <button
                    type="button"
                    onClick={() =>
                      navigate(`/projects/${id}/sessions/${s.id}`)
                    }
                    className="o-list-row flex min-w-0 flex-1 items-center justify-between gap-4 px-4 py-3 text-left"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium text-[var(--o-text)]">
                        {s.title}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-[var(--o-text-tertiary)]">
                        {s.model ?? "Default model"}
                      </p>
                    </div>
                    <SessionStatusBadge status={s.status} />
                  </button>
                  {canWrite && (
                    <button
                      type="button"
                      title="Delete session"
                      disabled={deleteSessionMut.isPending}
                      className="shrink-0 border-l border-[var(--o-border)] px-3 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-danger)]/8 hover:text-[var(--o-danger)] disabled:opacity-40"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSessionToDelete(s);
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === "Context Hub" && (
        <ProjectContextHub projectId={id!} readOnly={!canWrite} />
      )}

      {tab === "Clusters" && (
        <ClusterManager projectId={id!} readOnly={!canWrite} />
      )}

      {tab === "Secrets" && (
        <VaultManager projectId={id!} readOnly={!canWrite} />
      )}

      {tab === "Sharing" && !isPublicProject && (
        <ProjectSharing projectId={id!} canManageShares={canAdmin} />
      )}

      {tab === "Settings" && <ProjectRuntimeSettingsPanel projectId={id!} />}

      {tab !== "Sessions" &&
        tab !== "Context Hub" &&
        tab !== "Clusters" &&
        tab !== "Secrets" &&
        tab !== "Sharing" &&
        tab !== "Settings" && (
        <div className="o-empty text-sm text-[var(--o-text-secondary)]">
          {tab} will appear here.
        </div>
      )}

      {editOpen && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          onClick={() => !updateMut.isPending && setEditOpen(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2 className="text-lg font-semibold text-[var(--o-text)]">
                Edit project
              </h2>
            </div>
            <form
              className="space-y-4 p-6"
              onSubmit={(e) => {
                e.preventDefault();
                if (!editName.trim() || updateMut.isPending) return;
                updateMut.mutate();
              }}
            >
              <div>
                <label htmlFor="edit-name" className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">Name</label>
                <input id="edit-name" value={editName} onChange={(e) => setEditName(e.target.value)} className="o-input w-full px-3 py-2.5 text-sm" />
              </div>
              <div>
                <label htmlFor="edit-desc" className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">Description</label>
                <textarea id="edit-desc" value={editDesc} onChange={(e) => setEditDesc(e.target.value)} rows={3} className="o-input w-full resize-none px-3 py-2.5 text-sm" />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" disabled={updateMut.isPending} onClick={() => setEditOpen(false)} className="o-btn-ghost rounded-lg px-4 py-2 text-sm">Cancel</button>
                <button type="submit" disabled={!editName.trim() || updateMut.isPending} className="o-btn-success inline-flex items-center gap-2 px-5 py-2 text-sm disabled:opacity-50">
                  {updateMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Save
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteProjectOpen && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          onClick={() => !deleteProjectMut.isPending && setDeleteProjectOpen(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-project-detail-title"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2
                id="delete-project-detail-title"
                className="text-lg font-semibold text-[var(--o-text)]"
              >
                Delete project?
              </h2>
              <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
                <span className="font-medium text-[var(--o-text)]">
                  {project.name}
                </span>{" "}
                and all sessions, messages, clusters, and shared access for
                this project will be permanently removed. This cannot be undone.
              </p>
            </div>
            {deleteProjectMut.isError && (
              <p className="px-6 pt-4 text-sm text-[var(--o-danger)]">
                {(deleteProjectMut.error as Error)?.message ?? "Delete failed."}
              </p>
            )}
            <div className="flex justify-end gap-2 px-6 py-5">
              <button
                type="button"
                disabled={deleteProjectMut.isPending}
                onClick={() => setDeleteProjectOpen(false)}
                className="o-btn-ghost rounded-lg px-4 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteProjectMut.isPending}
                onClick={() => deleteProjectMut.mutate()}
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--o-danger)]/40 bg-[var(--o-danger)]/10 px-4 py-2 text-sm font-medium text-[var(--o-danger)] hover:bg-[var(--o-danger)]/20 disabled:opacity-50"
              >
                {deleteProjectMut.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                Delete project
              </button>
            </div>
          </div>
        </div>
      )}

      {sessionToDelete && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          onClick={() => !deleteSessionMut.isPending && setSessionToDelete(null)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-session-title"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2
                id="delete-session-title"
                className="text-lg font-semibold text-[var(--o-text)]"
              >
                Delete session?
              </h2>
              <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
                <span className="font-medium text-[var(--o-text)]">
                  {sessionToDelete.title}
                </span>{" "}
                and its chat history and context layers will be removed. This
                cannot be undone.
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
                onClick={() => setSessionToDelete(null)}
                className="o-btn-ghost rounded-lg px-4 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteSessionMut.isPending}
                onClick={() => deleteSessionMut.mutate(sessionToDelete.id)}
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

      {sessionModal && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          onClick={() => !createSessionMut.isPending && setSessionModal(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2 className="text-lg font-semibold text-[var(--o-text)]">New session</h2>
              <p className="mt-1 text-sm text-[var(--o-text-secondary)]">Choose a title and a default model for this session.</p>
            </div>
            <form
              className="space-y-4 p-6"
              onSubmit={(e) => {
                e.preventDefault();
                if (!sessionTitle.trim() || createSessionMut.isPending) return;
                createSessionMut.mutate();
              }}
            >
              <div>
                <label htmlFor="sess-title" className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">Title</label>
                <input id="sess-title" value={sessionTitle} onChange={(e) => setSessionTitle(e.target.value)} className="o-input w-full px-3 py-2.5 text-sm" placeholder="e.g. Refactor auth module" autoFocus />
              </div>
              <div>
                <label htmlFor="sess-model" className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">Model</label>
                <select id="sess-model" value={sessionModel} onChange={(e) => setSessionModel(e.target.value)} className="o-input w-full px-3 py-2.5 text-sm">
                  {SESSION_MODELS.map((m) => (<option key={m.id} value={m.id}>{m.label}</option>))}
                </select>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" disabled={createSessionMut.isPending} onClick={() => setSessionModal(false)} className="o-btn-ghost rounded-lg px-4 py-2 text-sm">Cancel</button>
                <button type="submit" disabled={!sessionTitle.trim() || createSessionMut.isPending} className="o-btn-primary inline-flex items-center gap-2 px-5 py-2 text-sm disabled:opacity-50">
                  {createSessionMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
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

function ProjectContextHub({
  projectId,
  readOnly,
}: {
  projectId: string;
  readOnly: boolean;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const installedQuery = useQuery({
    queryKey: ["installed-packs", projectId],
    queryFn: () => listInstalledPacks(projectId),
    enabled: Boolean(projectId),
  });

  const uninstallMut = useMutation({
    mutationFn: (packId: string) => uninstallPack(projectId, packId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["installed-packs", projectId],
      });
      queryClient.invalidateQueries({
        queryKey: ["context-sources", projectId],
      });
    },
  });

  const installed = installedQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
          Installed Packs
        </h2>
        <button
          type="button"
          onClick={() => navigate("/hub")}
          className="o-btn-ghost inline-flex items-center gap-2 border border-[var(--o-border)] px-3 py-2 text-sm hover:border-[var(--o-accent)]/40 hover:shadow-sm"
        >
          {!readOnly && <Plus className="h-4 w-4" />}
          Browse Hub
        </button>
      </div>

      {installedQuery.isLoading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--o-text-secondary)]" />
        </div>
      ) : installed.length === 0 ? (
        <div className="o-empty text-sm text-[var(--o-text-secondary)]">
          No packs installed. Browse the Context Hub to add knowledge packs.
        </div>
      ) : (
        <ul className="o-list divide-y divide-[var(--o-border)]">
          {installed.map((ip: InstalledPack) => (
            <li
              key={ip.id}
              className="o-list-row flex items-center justify-between gap-4 px-4 py-3"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--o-accent-muted)] text-[var(--o-accent)]">
                  {ip.pack.icon ? (
                    <span className="text-sm">{ip.pack.icon}</span>
                  ) : (
                    <Package className="h-4 w-4" />
                  )}
                </div>
                <div className="min-w-0">
                  <button
                    type="button"
                    onClick={() => navigate(`/hub/${ip.pack_id}`)}
                    className="truncate text-sm font-medium text-[var(--o-text)] hover:text-[var(--o-accent)]"
                  >
                    {ip.pack.name}
                  </button>
                  <p className="text-xs text-[var(--o-text-tertiary)]">
                    v{ip.version} &middot; {ip.pack.sources.length} sources
                  </p>
                </div>
              </div>
              {!readOnly && (
                <button
                  type="button"
                  onClick={() => uninstallMut.mutate(ip.pack_id)}
                  disabled={uninstallMut.isPending}
                  className="shrink-0 rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-danger)]/10 hover:text-[var(--o-danger)]"
                  title="Uninstall pack from this project"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <ContextManager projectId={projectId} readOnly={readOnly} />
    </div>
  );
}

