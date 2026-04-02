import {
  deletePack,
  getPack,
  installPack,
  listPackInstallations,
  uninstallPack,
} from "@/api/contextHub";
import { listProjects } from "@/api/projects";
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
  Pencil,
  Trash2,
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

function ProjectPickerButton({ packId }: { packId: string }) {
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
    onSuccess: (_data, projectId) => {
      queryClient.invalidateQueries({ queryKey: ["installed-packs"] });
      queryClient.invalidateQueries({
        queryKey: ["context-sources", projectId],
      });
      queryClient.invalidateQueries({
        queryKey: ["pack-installations", packId],
      });
      queryClient.invalidateQueries({ queryKey: ["pack", packId] });
      setOpen(false);
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
        className="o-btn-success inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
      >
        {installMut.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Download className="h-4 w-4" />
        )}
        Install pack
        <ChevronDown className="h-3.5 w-3.5" />
      </button>

      {open && (
        <div className="o-dropdown absolute right-0 top-full z-50 mt-1 w-72">
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
            <p className="px-3 py-4 text-center text-xs text-[var(--o-text-tertiary)]">
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
                    className="o-list-row flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[var(--o-text)]"
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
  const queryClient = useQueryClient();
  const [deleteOpen, setDeleteOpen] = useState(false);

  const packQuery = useQuery({
    queryKey: ["pack", packId],
    queryFn: () => getPack(packId!),
    enabled: Boolean(packId),
  });

  const installationsQuery = useQuery({
    queryKey: ["pack-installations", packId],
    queryFn: () => listPackInstallations(packId!),
    enabled: Boolean(packId),
  });

  const uninstallMut = useMutation({
    mutationFn: ({
      projectId,
    }: {
      projectId: string;
    }) => uninstallPack(projectId, packId!),
    onSuccess: (_void, { projectId }) => {
      queryClient.invalidateQueries({
        queryKey: ["pack-installations", packId],
      });
      queryClient.invalidateQueries({ queryKey: ["installed-packs"] });
      queryClient.invalidateQueries({
        queryKey: ["context-sources", projectId],
      });
      queryClient.invalidateQueries({ queryKey: ["pack", packId] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => deletePack(packId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["packs"] });
      queryClient.invalidateQueries({ queryKey: ["pack-installations", packId] });
      setDeleteOpen(false);
      navigate("/hub");
    },
  });

  if (packQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--o-text-secondary)]" />
      </div>
    );
  }

  const pack = packQuery.data;
  if (!pack) {
    return (
      <div className="p-8 text-sm text-[var(--o-danger)]">Pack not found.</div>
    );
  }

  const installations = installationsQuery.data ?? [];
  const blockCatalogDelete =
    deleteMut.isPending ||
    installationsQuery.isLoading ||
    (installationsQuery.isSuccess && installations.length > 0);

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

        <div className="flex flex-col items-end gap-2">
          {installations.length > 0 && (
            <div className="o-badge o-badge-green inline-flex items-center gap-2 px-4 py-2 text-sm font-medium">
              <Check className="h-4 w-4" />
              Installed on {installations.length} project
              {installations.length === 1 ? "" : "s"}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => navigate(`/hub/${packId}/edit`)}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-4 py-2 text-sm font-medium text-[var(--o-text)] transition-colors hover:border-[var(--o-accent)]/40"
            >
              <Pencil className="h-4 w-4" />
              Edit pack
            </button>
            <ProjectPickerButton packId={packId!} />
          </div>
        </div>
      </div>

      {installations.length > 0 && (
        <div className="o-panel mb-8 p-5">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]">
            Uninstall from project
          </h2>
          <p className="mb-4 text-sm text-[var(--o-text-tertiary)]">
            Removes this pack and the context sources it added to that project.
          </p>
          {installationsQuery.isLoading ? (
            <div className="flex justify-center py-4">
              <Loader2 className="h-6 w-6 animate-spin text-[var(--o-text-secondary)]" />
            </div>
          ) : (
            <ul className="divide-y divide-[var(--o-border)] rounded-lg border border-[var(--o-border)]">
              {installations.map((row) => (
                <li
                  key={row.project_id}
                  className="flex items-center justify-between gap-3 px-4 py-3"
                >
                  <span className="min-w-0 truncate text-sm font-medium text-[var(--o-text)]">
                    {row.project_name}
                  </span>
                  <button
                    type="button"
                    disabled={uninstallMut.isPending}
                    onClick={() =>
                      uninstallMut.mutate({ projectId: row.project_id })
                    }
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--o-border)] px-3 py-1.5 text-xs font-medium text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-danger)]/40 hover:bg-[var(--o-danger)]/10 hover:text-[var(--o-danger)] disabled:opacity-50"
                  >
                    {uninstallMut.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                    Uninstall
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {pack.description && (
        <div className="o-panel mb-8 p-5">
          <p className="text-sm leading-relaxed text-[var(--o-text)]">
            {pack.description}
          </p>
        </div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]">
          Sources ({pack.sources.length})
        </h2>
        <span className="text-xs text-[var(--o-text-secondary)]">
          {pack.repo_count} repos
        </span>
      </div>

      {pack.sources.length === 0 ? (
        <div className="o-empty text-sm text-[var(--o-text-secondary)]">
          This pack has no sources yet.
        </div>
      ) : (
        <ul className="o-list divide-y divide-[var(--o-border)]">
          {pack.sources.map((src) => {
            const SrcIcon = SOURCE_ICON[src.type] ?? FileText;
            return (
              <li
                key={src.id}
                className="o-list-row flex items-center gap-3 px-4 py-3"
              >
                <SrcIcon className="h-4 w-4 shrink-0 text-[var(--o-text-secondary)]" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-[var(--o-text)]">
                    {src.name}
                  </p>
                  {src.url && (
                    <p className="break-all text-xs font-mono leading-snug text-[var(--o-accent)] [text-wrap:pretty]">
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

      <div className="mt-10 rounded-xl border border-[var(--o-danger)]/25 bg-[var(--o-danger)]/5 p-5">
        <h2 className="text-sm font-semibold text-[var(--o-text)]">
          Delete pack from catalog
        </h2>
        <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
          Permanently removes this pack definition from the Context Hub. You can
          only do this after it has been uninstalled from every project.
        </p>
        {installationsQuery.isSuccess && installations.length > 0 && (
          <p className="mt-2 text-sm text-amber-800 dark:text-amber-200">
            Uninstall from all {installations.length} project
            {installations.length === 1 ? "" : "s"} first, then delete.
          </p>
        )}
        {installationsQuery.isFetching && !installationsQuery.isSuccess && (
          <p className="mt-2 text-xs text-[var(--o-text-tertiary)]">
            Checking installations…
          </p>
        )}
        <button
          type="button"
          disabled={blockCatalogDelete}
          onClick={() => setDeleteOpen(true)}
          className={clsx(
            "mt-4 inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-colors",
            !blockCatalogDelete
              ? "border-[var(--o-danger)]/40 text-[var(--o-danger)] hover:bg-[var(--o-danger)]/10"
              : "cursor-not-allowed border-[var(--o-border)] text-[var(--o-text-tertiary)] opacity-60",
          )}
        >
          {deleteMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
          Delete pack
        </button>
        {deleteMut.isError && (
          <p className="mt-3 text-sm text-[var(--o-danger)]">
            {(deleteMut.error as { response?: { data?: { detail?: string } } })
              ?.response?.data?.detail ??
              (deleteMut.error as Error)?.message ??
              "Could not delete pack."}
          </p>
        )}
      </div>

      {deleteOpen && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          role="presentation"
          onClick={() => !deleteMut.isPending && setDeleteOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2 className="text-lg font-semibold text-[var(--o-text)]">
                Delete “{pack.name}”?
              </h2>
              <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
                This cannot be undone. Projects will no longer be able to
                install this pack from the catalog.
              </p>
            </div>
            <div className="flex justify-end gap-2 px-6 py-5">
              <button
                type="button"
                disabled={deleteMut.isPending}
                onClick={() => setDeleteOpen(false)}
                className="o-btn-ghost rounded-lg px-4 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteMut.isPending}
                onClick={() => deleteMut.mutate()}
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--o-danger)]/40 bg-[var(--o-danger)]/10 px-4 py-2 text-sm font-medium text-[var(--o-danger)] hover:bg-[var(--o-danger)]/20 disabled:opacity-50"
              >
                {deleteMut.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                Delete permanently
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
