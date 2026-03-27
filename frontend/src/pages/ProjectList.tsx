import { createProject, deleteProject, listProjects } from "@/api/projects";
import {
  canAdminProject,
  effectiveProjectAccess,
} from "@/lib/projectAccess";
import {
  readRecentSessions,
  removeRecentSessionsForProject,
} from "@/lib/recentSessions";
import type { Project } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FolderKanban, History, Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
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

export default function ProjectList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["projects"],
    queryFn: () => listProjects(),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createProject({
        name: name.trim(),
        description: description.trim() || undefined,
      }),
    onSuccess: (project: Project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setModalOpen(false);
      setName("");
      setDescription("");
      navigate(`/projects/${project.id}`);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (projectId: string) => deleteProject(projectId),
    onSuccess: (_void, deletedId) => {
      removeRecentSessionsForProject(deletedId);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setDeleteTarget(null);
    },
  });

  const projects = data ?? [];
  const recentSessions = readRecentSessions();
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
        <div className="mb-8 rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-4">
          <div className="mb-3 flex items-center gap-2">
            <History className="h-4 w-4 text-[var(--o-accent)]" />
            <h2 className="text-sm font-semibold text-[var(--o-text)]">
              Recent sessions
            </h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {recentSessions.map((r) => {
              const labelProject =
                projectNames.get(r.projectId) ?? r.projectName;
              return (
                <button
                  key={`${r.projectId}-${r.sessionId}`}
                  type="button"
                  onClick={() =>
                    navigate(`/projects/${r.projectId}/sessions/${r.sessionId}`)
                  }
                  className="group flex max-w-full flex-col rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-3 py-2 text-left transition-colors hover:border-[var(--o-accent)]/40 hover:bg-[var(--o-accent-muted)]"
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
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p: Project) => (
            <li key={p.id}>
              <div
                className="o-card-hover group relative flex h-full w-full flex-col rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] text-left"
                style={{ backgroundImage: "var(--o-gradient-card)" }}
              >
                {canAdminProject(effectiveProjectAccess(p)) && (
                  <button
                    type="button"
                    title="Delete project"
                    disabled={deleteMut.isPending}
                    className="absolute right-3 top-3 z-10 rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-danger)]/10 hover:text-[var(--o-danger)] disabled:opacity-40"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setDeleteTarget(p);
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => navigate(`/projects/${p.id}`)}
                  className={clsx(
                    "flex flex-1 flex-col p-5 text-left",
                    canAdminProject(effectiveProjectAccess(p)) && "pr-12",
                  )}
                >
                  <div className="mb-3 flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--o-accent-muted)] text-[var(--o-accent)]">
                        <FolderKanban className="h-4 w-4" />
                      </span>
                      <span className="font-semibold text-[var(--o-text)] transition-colors group-hover:text-[var(--o-accent)]">
                        {p.name}
                      </span>
                    </div>
                  </div>
                  <p className="mb-4 line-clamp-2 flex-1 text-sm text-[var(--o-text-secondary)]">
                    {p.description?.trim() || "No description"}
                  </p>
                  <div className="flex items-center justify-between border-t border-[var(--o-border)] pt-3 text-xs text-[var(--o-text-tertiary)]">
                    <span>
                      {p.session_count ?? 0}{" "}
                      {(p.session_count ?? 0) === 1 ? "session" : "sessions"}
                    </span>
                    <span>Updated {formatDate(p.updated_at)}</span>
                  </div>
                </button>
              </div>
            </li>
          ))}
        </ul>
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
                Name your workspace and add an optional description.
              </p>
            </div>
            <form
              className="space-y-4 p-6"
              onSubmit={(e) => {
                e.preventDefault();
                if (!name.trim() || createMut.isPending) return;
                createMut.mutate();
              }}
            >
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
                  disabled={!name.trim() || createMut.isPending}
                  className={clsx(
                    "o-btn-primary inline-flex items-center gap-2 px-5 py-2 text-sm",
                    (!name.trim() || createMut.isPending) && "cursor-not-allowed opacity-50"
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
