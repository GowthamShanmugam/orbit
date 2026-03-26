import { listProjects } from "@/api/projects";
import { getPack, installPack } from "@/api/contextHub";
import type { Project } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowLeft,
  Check,
  ChevronDown,
  Database,
  Download,
  FileText,
  GitBranch,
  Loader2,
  Package,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

const SOURCE_TYPE_LABELS: Record<string, string> = {
  github_repo: "GitHub Repo",
  gitlab_repo: "GitLab Repo",
  jira_project: "Jira Project",
  confluence_space: "Confluence Space",
  google_doc: "Google Doc",
  google_drive_folder: "Google Drive",
  file_pin: "Pinned File",
  code_snippet: "Code Snippet",
};

const SOURCE_ICON: Record<string, typeof Database> = {
  github_repo: GitBranch,
  gitlab_repo: GitBranch,
  jira_project: FileText,
  confluence_space: FileText,
  google_doc: FileText,
  google_drive_folder: Database,
  file_pin: FileText,
  code_snippet: FileText,
};

function ProjectPickerButton({
  packId,
  onInstalled,
}: {
  packId: string;
  onInstalled: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
    enabled: open,
  });

  const installMut = useMutation({
    mutationFn: (projectId: string) => installPack(projectId, packId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["installed-packs"] });
      setOpen(false);
      onInstalled();
    },
  });

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const projects = projectsQuery.data ?? [];

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={installMut.isPending}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-2 rounded-md bg-[var(--o-green-bg)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--o-green-bg-hover)] disabled:opacity-50"
      >
        {installMut.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Download className="h-4 w-4" />
        )}
        Install Pack
        <ChevronDown className="h-3.5 w-3.5" />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-72 overflow-hidden rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-xl">
          <div className="border-b border-[var(--o-border)] px-3 py-2">
            <p className="text-xs font-medium text-[var(--o-text-secondary)]">
              Install to project
            </p>
          </div>
          {projectsQuery.isLoading ? (
            <div className="flex justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--o-text-secondary)]" />
            </div>
          ) : projects.length === 0 ? (
            <p className="px-3 py-4 text-center text-xs text-[var(--o-border-subtle)]">
              No projects found. Create a project first.
            </p>
          ) : (
            <ul className="max-h-60 overflow-y-auto py-1">
              {projects.map((p: Project) => (
                <li key={p.id}>
                  <button
                    type="button"
                    disabled={installMut.isPending}
                    onClick={() => installMut.mutate(p.id)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[var(--o-text)] transition-colors hover:bg-[var(--o-bg-subtle)]"
                  >
                    <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function PackDetail() {
  const { packId } = useParams<{ packId: string }>();
  const navigate = useNavigate();
  const [installed, setInstalled] = useState(false);

  const packQuery = useQuery({
    queryKey: ["pack", packId],
    queryFn: () => getPack(packId!),
    enabled: Boolean(packId),
  });

  const pack = packQuery.data;

  if (packQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--o-text-secondary)]" />
      </div>
    );
  }

  if (!pack) {
    return (
      <div className="p-8 text-sm text-[var(--o-danger)]">Pack not found.</div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <button
        type="button"
        onClick={() => navigate("/hub")}
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-[var(--o-text-secondary)] transition-colors hover:text-[var(--o-accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to catalog
      </button>

      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-[var(--o-bg-subtle)] text-[var(--o-accent)]">
            {pack.icon ? (
              <span className="text-2xl">{pack.icon}</span>
            ) : (
              <Package className="h-7 w-7" />
            )}
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-[var(--o-text)]">
              {pack.name}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-[var(--o-text-secondary)]">
              {pack.category && (
                <span className="rounded-full bg-[var(--o-bg-subtle)] px-2.5 py-0.5 text-xs font-medium">
                  {pack.category}
                </span>
              )}
              <span>v{pack.version}</span>
              <span>{pack.visibility}</span>
              {pack.maintainer_team && (
                <span>by {pack.maintainer_team}</span>
              )}
            </div>
          </div>
        </div>

        {installed ? (
          <div className="inline-flex items-center gap-2 rounded-md border border-[var(--o-green-bg)]/50 bg-[var(--o-green-bg)]/10 px-4 py-2 text-sm font-medium text-[var(--o-green)]">
            <Check className="h-4 w-4" />
            Installed
          </div>
        ) : (
          <ProjectPickerButton
            packId={packId!}
            onInstalled={() => setInstalled(true)}
          />
        )}
      </div>

      {pack.description && (
        <div className="mb-8 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-5">
          <p className="text-sm leading-relaxed text-[var(--o-text)]">
            {pack.description}
          </p>
        </div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]">
          Sources ({pack.sources.length})
        </h2>
        <span className="text-xs text-[var(--o-border-subtle)]">
          {pack.repo_count} repos
        </span>
      </div>

      {pack.sources.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--o-border)] bg-[var(--o-bg-raised)]/40 px-6 py-10 text-center text-sm text-[var(--o-text-secondary)]">
          This pack has no sources yet.
        </div>
      ) : (
        <ul className="divide-y divide-[var(--o-border)] overflow-hidden rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)]">
          {pack.sources.map((src) => {
            const SrcIcon = SOURCE_ICON[src.type] ?? FileText;
            return (
              <li
                key={src.id}
                className="flex items-center gap-3 px-4 py-3"
              >
                <SrcIcon className="h-4 w-4 shrink-0 text-[var(--o-text-secondary)]" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-[var(--o-text)]">
                    {src.name}
                  </p>
                  {src.url && (
                    <p className="truncate text-xs text-[var(--o-border-subtle)]">
                      {src.url}
                    </p>
                  )}
                </div>
                <span className="shrink-0 rounded bg-[var(--o-bg-subtle)] px-2 py-0.5 text-[10px] font-medium text-[var(--o-text-secondary)]">
                  {SOURCE_TYPE_LABELS[src.type] ?? src.type}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {pack.dependencies &&
        Object.keys(pack.dependencies).length > 0 && (
          <div className="mt-8">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]">
              Dependencies
            </h2>
            <div className="flex flex-wrap gap-2">
              {Object.entries(pack.dependencies).map(([name, ver]) => (
                <span
                  key={name}
                  className="rounded-md border border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-3 py-1 text-xs text-[var(--o-text)]"
                >
                  {name} {ver ? `v${ver}` : ""}
                </span>
              ))}
            </div>
          </div>
        )}
    </div>
  );
}
