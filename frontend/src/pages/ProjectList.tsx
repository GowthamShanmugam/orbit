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
          <h1 className="text-2xl font-semibold tracking-tight text-[#e6edf3]">
            Projects
          </h1>
          <p className="mt-1 text-sm text-[#8b949e]">
            Organize work and spin up AI sessions per codebase.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="inline-flex items-center gap-2 rounded-md bg-[#238636] px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#2ea043]"
        >
          <Plus className="h-4 w-4" />
          New Project
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-24 text-[#8b949e]">
          <Loader2 className="h-8 w-8 animate-spin" />
        </div>
      )}

      {isError && (
        <div className="rounded-lg border border-[#f85149]/40 bg-[#f85149]/10 px-4 py-3 text-sm text-[#f85149]">
          {(error as Error)?.message ?? "Could not load projects."}
        </div>
      )}

      {!isLoading && !isError && projects.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#30363d] bg-[#161b22]/50 px-8 py-20 text-center">
          <Sparkles className="mb-4 h-12 w-12 text-[#58a6ff]/80" />
          <h2 className="text-lg font-medium text-[#e6edf3]">
            No projects yet
          </h2>
          <p className="mt-2 max-w-md text-sm text-[#8b949e]">
            Create a project to connect your repository context, sessions, and
            workflows. Your AI IDE workspace starts here.
          </p>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="mt-6 inline-flex items-center gap-2 rounded-md border border-[#30363d] bg-[#21262d] px-4 py-2 text-sm font-medium text-[#e6edf3] transition-colors hover:border-[#58a6ff]/50 hover:bg-[#30363d]"
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
                className="group flex h-full w-full flex-col rounded-lg border border-[#30363d] bg-[#161b22] p-5 text-left transition-all hover:border-[#58a6ff]/40 hover:shadow-lg hover:shadow-black/20"
              >
                <div className="mb-3 flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#21262d] text-[#58a6ff] transition-colors group-hover:bg-[#30363d]">
                      <FolderKanban className="h-4 w-4" />
                    </span>
                    <span className="font-semibold text-[#e6edf3] transition-colors group-hover:text-[#58a6ff]">
                      {p.name}
                    </span>
                  </div>
                </div>
                <p className="mb-4 line-clamp-2 flex-1 text-sm text-[#8b949e]">
                  {p.description?.trim() || "No description"}
                </p>
                <div className="flex items-center justify-between border-t border-[#30363d] pt-3 text-xs text-[#8b949e]">
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
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          role="presentation"
          onClick={() => !createMut.isPending && setModalOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-project-title"
            className="w-full max-w-md rounded-lg border border-[#30363d] bg-[#161b22] shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[#30363d] px-5 py-4">
              <h2
                id="new-project-title"
                className="text-lg font-semibold text-[#e6edf3]"
              >
                New project
              </h2>
              <p className="mt-1 text-sm text-[#8b949e]">
                Name your workspace and add an optional description.
              </p>
            </div>
            <form
              className="space-y-4 p-5"
              onSubmit={(e) => {
                e.preventDefault();
                if (!name.trim() || createMut.isPending) return;
                createMut.mutate();
              }}
            >
              <div>
                <label
                  htmlFor="project-name"
                  className="mb-1.5 block text-xs font-medium text-[#8b949e]"
                >
                  Name
                </label>
                <input
                  id="project-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full rounded-md border border-[#30363d] bg-[#0d1117] px-3 py-2 text-sm text-[#e6edf3] outline-none ring-[#58a6ff] transition-colors focus:border-[#58a6ff] focus:ring-1"
                  placeholder="e.g. orbit-core"
                  autoFocus
                />
              </div>
              <div>
                <label
                  htmlFor="project-desc"
                  className="mb-1.5 block text-xs font-medium text-[#8b949e]"
                >
                  Description
                </label>
                <textarea
                  id="project-desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="w-full resize-none rounded-md border border-[#30363d] bg-[#0d1117] px-3 py-2 text-sm text-[#e6edf3] outline-none ring-[#58a6ff] transition-colors focus:border-[#58a6ff] focus:ring-1"
                  placeholder="What lives in this project?"
                />
              </div>
              {createMut.isError && (
                <p className="text-sm text-[#f85149]">
                  {(createMut.error as Error)?.message ?? "Create failed"}
                </p>
              )}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={createMut.isPending}
                  onClick={() => setModalOpen(false)}
                  className="rounded-md px-3 py-2 text-sm font-medium text-[#8b949e] transition-colors hover:bg-[#21262d] hover:text-[#e6edf3]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!name.trim() || createMut.isPending}
                  className={clsx(
                    "inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-white transition-colors",
                    !name.trim() || createMut.isPending
                      ? "cursor-not-allowed bg-[#238636]/50"
                      : "bg-[#238636] hover:bg-[#2ea043]"
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
