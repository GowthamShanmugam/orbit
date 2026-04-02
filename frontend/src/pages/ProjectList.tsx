import { createProject, deleteProject, listProjects } from "@/api/projects";
import ProjectWorkspaceBadge from "@/components/ProjectWorkspaceBadge";
import {
  canAdminProject,
  effectiveProjectAccess,
} from "@/lib/projectAccess";
import {
  pruneRecentSessionsToKnownProjects,
  readRecentSessions,
  removeRecentSessionsForProject,
} from "@/lib/recentSessions";
import type { Project } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ChevronDown,
  FolderKanban,
  Globe,
  History,
  Loader2,
  Plus,
  Share2,
  Sparkles,
  Trash2,
  User,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

function formatDate(iso: string) {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function isPublicProject(p: Project) {
  return (p.visibility ?? "private") === "public";
}

type ProjectSectionKey = "recent" | "shared" | "private" | "public";

function CollapsibleGroup({
  title,
  count,
  expanded,
  onToggle,
  headerExtra,
  titleClassName,
  children,
}: {
  title: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  headerExtra?: ReactNode;
  /** Defaults to catalog section label style */
  titleClassName?: string;
  children: ReactNode;
}) {
  const headingClass =
    titleClassName ??
    "text-sm font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]";
  return (
    <div
      className="rounded-xl bg-[var(--o-bg-raised)] p-4"
      style={{ boxShadow: "var(--o-shadow-sm)" }}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start justify-between gap-3 rounded-lg text-left transition-colors hover:bg-[var(--o-bg-subtle)]/80"
        aria-expanded={expanded}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {headerExtra}
            <h2 className={headingClass}>{title}</h2>
            <span className="rounded-md bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-[var(--o-text-tertiary)]">
              {count}
            </span>
          </div>
        </div>
        <ChevronDown
          className={clsx(
            "mt-0.5 h-5 w-5 shrink-0 text-[var(--o-text-tertiary)] transition-transform duration-200",
            expanded ? "rotate-0" : "-rotate-90",
          )}
          aria-hidden
        />
      </button>
      {expanded ? <div className="mt-4">{children}</div> : null}
    </div>
  );
}

function ProjectListCard({
  project: p,
  variant,
  deletePending,
  onDelete,
  onOpen,
}: {
  project: Project;
  variant: "standard" | "shared";
  deletePending: boolean;
  onDelete: () => void;
  onOpen: () => void;
}) {
  const access = effectiveProjectAccess(p);
  const canDel = canAdminProject(access);
  const isShared = variant === "shared";
  const isPub = isPublicProject(p);
  const ownerDisplay = p.created_by_display?.trim() || "Teammate";

  return (
    <div
      className={clsx(
        "o-card-hover group relative flex h-full w-full flex-col rounded-xl border text-left bg-[var(--o-bg-raised)]",
        isShared
          ? "border-amber-500/35 ring-1 ring-amber-500/15"
          : isPub
            ? "border-emerald-500/25 ring-1 ring-emerald-500/10"
            : "border-[var(--o-border)]",
      )}
      style={{ backgroundImage: "var(--o-gradient-card)" }}
    >
      {canDel && (
        <button
          type="button"
          title="Delete project"
          disabled={deletePending}
          className="absolute right-3 top-3 z-10 rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-danger)]/10 hover:text-[var(--o-danger)] disabled:opacity-40"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDelete();
          }}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
      <button
        type="button"
        onClick={onOpen}
        className={clsx(
          "flex flex-1 flex-col p-5 text-left",
          canDel && "pr-12",
        )}
      >
        <div className="mb-3 flex min-w-0 gap-3">
          <span
            className={clsx(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl shadow-sm",
              isShared
                ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                : isPub
                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                  : "bg-[var(--o-accent-muted)] text-[var(--o-accent)]",
            )}
          >
            {isShared ? (
              <Share2 className="h-[18px] w-[18px]" />
            ) : isPub ? (
              <Globe className="h-[18px] w-[18px]" />
            ) : (
              <FolderKanban className="h-[18px] w-[18px]" />
            )}
          </span>
          <div className="min-w-0 flex-1">
            <h3
              className="truncate text-base font-semibold text-[var(--o-text)] transition-colors group-hover:text-[var(--o-accent)]"
              title={p.name}
            >
              {p.name}
            </h3>
            {isShared && (
              <p className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-[var(--o-text-secondary)]">
                <User
                  className="h-3.5 w-3.5 shrink-0 text-[var(--o-text-tertiary)]"
                  aria-hidden
                />
                <span className="shrink-0 text-[var(--o-text-tertiary)]">
                  Shared by
                </span>
                <span
                  className="min-w-0 truncate font-medium text-[var(--o-text)]"
                  title={ownerDisplay}
                >
                  {ownerDisplay}
                </span>
              </p>
            )}
          </div>
        </div>
        <div className="mb-2 min-w-0">
          <ProjectWorkspaceBadge
            project={p}
            presentation="inline"
            className="w-full"
          />
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-[var(--o-text-tertiary)]">
          <span>
            {p.session_count ?? 0}{" "}
            {(p.session_count ?? 0) === 1 ? "session" : "sessions"}
          </span>
          <span>Updated {formatDate(p.updated_at)}</span>
        </div>
      </button>
    </div>
  );
}

export default function ProjectList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"private" | "public">(
    "private",
  );
  const [sectionsOpen, setSectionsOpen] = useState<
    Record<ProjectSectionKey, boolean>
  >({
    recent: true,
    shared: true,
    private: true,
    public: true,
  });

  const toggleSection = (key: ProjectSectionKey) => {
    setSectionsOpen((s) => ({ ...s, [key]: !s[key] }));
  };

  useEffect(() => {
    if (modalOpen) {
      setVisibility("private");
    }
  }, [modalOpen]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["projects"],
    queryFn: () => listProjects(),
  });

  const projects = data ?? [];
  const { sharedProjects, privateProjects, publicProjects } = useMemo(() => {
    const shared: Project[] = [];
    const priv: Project[] = [];
    const pub: Project[] = [];
    for (const p of projects) {
      if (p.shared_with_me) {
        shared.push(p);
        continue;
      }
      if (isPublicProject(p)) pub.push(p);
      else priv.push(p);
    }
    return {
      sharedProjects: shared,
      privateProjects: priv,
      publicProjects: pub,
    };
  }, [projects]);
  const projectIds = useMemo(
    () => new Set(projects.map((p) => p.id)),
    [projects],
  );

  useEffect(() => {
    if (isLoading || isError) return;
    pruneRecentSessionsToKnownProjects(projectIds);
  }, [isLoading, isError, projectIds]);

  const recentSessions = useMemo(() => {
    if (isLoading || isError) return [];
    return readRecentSessions().filter((r) => projectIds.has(r.projectId));
  }, [isLoading, isError, projectIds]);

  const createMut = useMutation({
    mutationFn: () =>
      createProject({
        name: name.trim(),
        description: description.trim() || undefined,
        visibility,
      }),
    onSuccess: (project: Project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setModalOpen(false);
      setName("");
      setDescription("");
      navigate(`/projects/${project.id}`);
    },
  });

  const canCreate = name.trim().length > 0;

  const deleteMut = useMutation({
    mutationFn: (projectId: string) => deleteProject(projectId),
    onSuccess: (_void, deletedId) => {
      removeRecentSessionsForProject(deletedId);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setDeleteTarget(null);
    },
  });

  const projectNames = new Map(projects.map((p) => [p.id, p.name]));

  return (
    <div className="mx-auto max-w-6xl p-8">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--o-text)]">
            Projects
          </h1>
          <p className="mt-1 text-sm text-[var(--o-text-secondary)]">
            Organize work and spin up AI sessions per codebase.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="o-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm"
        >
          <Plus className="h-4 w-4" />
          New Project
        </button>
      </div>

      {!isLoading && !isError && recentSessions.length > 0 && (
        <div className="mb-8">
          <CollapsibleGroup
            title="Recent sessions"
            count={recentSessions.length}
            expanded={sectionsOpen.recent}
            onToggle={() => toggleSection("recent")}
            headerExtra={
              <History className="h-4 w-4 shrink-0 text-[var(--o-accent)]" />
            }
            titleClassName="text-sm font-semibold text-[var(--o-text)]"
          >
            <div className="flex flex-wrap gap-2">
              {recentSessions.map((r) => {
                const labelProject =
                  projectNames.get(r.projectId) ?? r.projectName;
                return (
                  <button
                    key={`${r.projectId}-${r.sessionId}`}
                    type="button"
                    onClick={() =>
                      navigate(
                        `/projects/${r.projectId}/sessions/${r.sessionId}`,
                      )
                    }
                    className="group flex max-w-full flex-col rounded-lg bg-[var(--o-bg-subtle)] px-3 py-2 text-left transition-colors hover:bg-[var(--o-accent-muted)]"
                  >
                    <span className="truncate text-sm font-medium text-[var(--o-text)] group-hover:text-[var(--o-accent)]">
                      {r.sessionTitle}
                    </span>
                    <span className="truncate text-[11px] text-[var(--o-text-tertiary)]">
                      {labelProject}
                    </span>
                  </button>
                );
              })}
            </div>
          </CollapsibleGroup>
        </div>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-24 text-[var(--o-text-secondary)]">
          <Loader2 className="h-8 w-8 animate-spin" />
        </div>
      )}

      {isError && (
        <div className="rounded-xl border border-[var(--o-danger)]/30 bg-[var(--o-danger)]/8 px-4 py-3 text-sm text-[var(--o-danger)]">
          {(error as Error)?.message ?? "Could not load projects."}
        </div>
      )}

      {!isLoading && !isError && projects.length === 0 && (
        <div className="o-empty flex flex-col items-center justify-center">
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--o-accent-muted)]">
            <Sparkles className="h-8 w-8 text-[var(--o-accent)]" />
          </div>
          <h2 className="text-lg font-medium text-[var(--o-text)]">
            No projects yet
          </h2>
          <p className="mt-2 max-w-md text-sm text-[var(--o-text-secondary)]">
            Create a project to connect your repository context, sessions, and
            workflows. Your AI IDE workspace starts here.
          </p>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="o-btn-primary mt-6 inline-flex items-center gap-2 px-4 py-2.5 text-sm"
          >
            <Plus className="h-4 w-4" />
            Create your first project
          </button>
        </div>
      )}

      {!isLoading && !isError && projects.length > 0 && (
        <div className="space-y-10">
          {sharedProjects.length > 0 && (
            <section>
              <CollapsibleGroup
                title="Shared with you"
                count={sharedProjects.length}
                expanded={sectionsOpen.shared}
                onToggle={() => toggleSection("shared")}
              >
                <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {sharedProjects.map((p: Project) => (
                    <li key={p.id}>
                      <ProjectListCard
                        project={p}
                        variant="shared"
                        deletePending={deleteMut.isPending}
                        onDelete={() => setDeleteTarget(p)}
                        onOpen={() => navigate(`/projects/${p.id}`)}
                      />
                    </li>
                  ))}
                </ul>
              </CollapsibleGroup>
            </section>
          )}
          {privateProjects.length > 0 && (
            <section>
              <CollapsibleGroup
                title="Private projects"
                count={privateProjects.length}
                expanded={sectionsOpen.private}
                onToggle={() => toggleSection("private")}
              >
                <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {privateProjects.map((p: Project) => (
                    <li key={p.id}>
                      <ProjectListCard
                        project={p}
                        variant="standard"
                        deletePending={deleteMut.isPending}
                        onDelete={() => setDeleteTarget(p)}
                        onOpen={() => navigate(`/projects/${p.id}`)}
                      />
                    </li>
                  ))}
                </ul>
              </CollapsibleGroup>
            </section>
          )}
          {publicProjects.length > 0 && (
            <section>
              <CollapsibleGroup
                title="Public projects"
                count={publicProjects.length}
                expanded={sectionsOpen.public}
                onToggle={() => toggleSection("public")}
              >
                <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {publicProjects.map((p: Project) => (
                    <li key={p.id}>
                      <ProjectListCard
                        project={p}
                        variant="standard"
                        deletePending={deleteMut.isPending}
                        onDelete={() => setDeleteTarget(p)}
                        onOpen={() => navigate(`/projects/${p.id}`)}
                      />
                    </li>
                  ))}
                </ul>
              </CollapsibleGroup>
            </section>
          )}
        </div>
      )}

      {modalOpen && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          role="presentation"
          onClick={() => !createMut.isPending && setModalOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-project-title"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2
                id="new-project-title"
                className="text-lg font-semibold text-[var(--o-text)]"
              >
                New project
              </h2>
              <p className="mt-1 text-sm text-[var(--o-text-secondary)]">
                Choose visibility, then name the project.
              </p>
            </div>
            <form
              className="space-y-4 p-6"
              onSubmit={(e) => {
                e.preventDefault();
                if (!canCreate || createMut.isPending) return;
                createMut.mutate();
              }}
            >
              <div>
                <span className="mb-2 block text-xs font-medium text-[var(--o-text-secondary)]">
                  Visibility
                </span>
                <div className="space-y-3">
                  <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-subtle)] p-3 has-[:checked]:border-[var(--o-accent)]/50 has-[:checked]:bg-[var(--o-accent-muted)]">
                    <input
                      type="radio"
                      name="project-visibility"
                      className="mt-0.5"
                      checked={visibility === "private"}
                      onChange={() => setVisibility("private")}
                    />
                    <span>
                      <span className="block text-sm font-medium text-[var(--o-text)]">
                        Private
                      </span>
                      <span className="mt-0.5 block text-xs text-[var(--o-text-secondary)]">
                        Only people you share with (or your org rules) can
                        access. Use the Sharing tab to invite collaborators.
                      </span>
                    </span>
                  </label>
                  <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-subtle)] p-3 has-[:checked]:border-[var(--o-accent)]/50 has-[:checked]:bg-[var(--o-accent-muted)]">
                    <input
                      type="radio"
                      name="project-visibility"
                      className="mt-0.5"
                      checked={visibility === "public"}
                      onChange={() => setVisibility("public")}
                    />
                    <span>
                      <span className="block text-sm font-medium text-[var(--o-text)]">
                        Public
                      </span>
                      <span className="mt-0.5 block text-xs text-[var(--o-text-secondary)]">
                        Anyone signed in can view. Only you can edit. The
                        Sharing tab is hidden because access is already public.
                      </span>
                    </span>
                  </label>
                </div>
              </div>
              <div>
                <label
                  htmlFor="project-name"
                  className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
                >
                  Name
                </label>
                <input
                  id="project-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="o-input w-full px-3 py-2.5 text-sm"
                  placeholder="e.g. orbit-core"
                  autoFocus
                />
              </div>
              <div>
                <label
                  htmlFor="project-desc"
                  className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
                >
                  Description
                </label>
                <textarea
                  id="project-desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="o-input w-full resize-none px-3 py-2.5 text-sm"
                  placeholder="What lives in this project?"
                />
              </div>
              {createMut.isError && (
                <p className="rounded-md bg-[var(--o-danger)]/10 px-3 py-2 text-sm text-[var(--o-danger)]">
                  {(createMut.error as Error)?.message ?? "Create failed"}
                </p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={createMut.isPending}
                  onClick={() => setModalOpen(false)}
                  className="o-btn-ghost rounded-lg px-4 py-2 text-sm"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!canCreate || createMut.isPending}
                  className={clsx(
                    "o-btn-primary inline-flex items-center gap-2 px-5 py-2 text-sm",
                    (!canCreate || createMut.isPending) &&
                      "cursor-not-allowed opacity-50",
                  )}
                >
                  {createMut.isPending && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  Create
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          role="presentation"
          onClick={() => !deleteMut.isPending && setDeleteTarget(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-project-title"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2
                id="delete-project-title"
                className="text-lg font-semibold text-[var(--o-text)]"
              >
                Delete project?
              </h2>
              <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
                <span className="font-medium text-[var(--o-text)]">
                  {deleteTarget.name}
                </span>{" "}
                and all of its sessions, messages, and related data will be
                permanently removed. This cannot be undone.
              </p>
            </div>
            {deleteMut.isError && (
              <p className="px-6 pt-4 text-sm text-[var(--o-danger)]">
                {(deleteMut.error as Error)?.message ?? "Delete failed."}
              </p>
            )}
            <div className="flex justify-end gap-2 px-6 py-5">
              <button
                type="button"
                disabled={deleteMut.isPending}
                onClick={() => setDeleteTarget(null)}
                className="o-btn-ghost rounded-lg px-4 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteMut.isPending}
                onClick={() => deleteMut.mutate(deleteTarget.id)}
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--o-danger)]/40 bg-[var(--o-danger)]/10 px-4 py-2 text-sm font-medium text-[var(--o-danger)] hover:bg-[var(--o-danger)]/20 disabled:opacity-50"
              >
                {deleteMut.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                Delete project
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
