import { createProject, listProjects } from "@/api/projects";
import type { Project } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FolderKanban, Loader2, Plus, Sparkles } from "lucide-react";
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

  const projects = data ?? [];

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
              <button
                type="button"
                onClick={() => navigate(`/projects/${p.id}`)}
                className="o-card-hover group flex h-full w-full flex-col rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-5 text-left"
                style={{ backgroundImage: "var(--o-gradient-card)" }}
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
    </div>
  );
}
