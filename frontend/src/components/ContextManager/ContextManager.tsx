import {
  addContextSource,
  addSessionLayer,
  cloneRepoSource,
  listContextSources,
  listSessionLayers,
  removeContextSource,
  removeSessionLayer,
} from "@/api/context";
import type {
  AddContextSourceInput,
  AddSessionLayerInput,
  ContextSourceType,
  SessionLayerType,
} from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Check,
  Database,
  FileText,
  GitBranch,
  Layers,
  Link2,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useState } from "react";

const SOURCE_TYPE_LABELS: Record<string, string> = {
  github_repo: "GitHub Repo",
  gitlab_repo: "GitLab Repo",
  jira_project: "Jira Project",
  confluence_space: "Confluence",
  google_doc: "Google Doc",
  google_drive_folder: "Google Drive",
  file_pin: "Pinned File",
  code_snippet: "Code Snippet",
};

const LAYER_TYPE_LABELS: Record<string, string> = {
  pull_request: "Pull Request",
  jira_ticket: "Jira Ticket",
  google_doc: "Google Doc",
  google_drive_folder: "Google Drive",
  file_pin: "Pinned File",
  code_snippet: "Code Snippet",
  past_session: "Past Session",
};

const SOURCE_ICONS: Record<string, typeof Database> = {
  github_repo: GitBranch,
  gitlab_repo: GitBranch,
  jira_project: FileText,
  pull_request: GitBranch,
  jira_ticket: FileText,
};

interface Props {
  projectId: string;
  sessionId?: string;
}

export default function ContextManager({ projectId, sessionId }: Props) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"sources" | "layers">(
    sessionId ? "layers" : "sources",
  );
  const [showAddSource, setShowAddSource] = useState(false);
  const [showAddLayer, setShowAddLayer] = useState(false);
  const [pollingEnabled, setPollingEnabled] = useState(false);

  const sourcesQuery = useQuery({
    queryKey: ["context-sources", projectId],
    queryFn: async () => {
      const data = await listContextSources(projectId);
      const anyCloning = data.some(
        (s) => s.config?.clone_status === "cloning",
      );
      setPollingEnabled(anyCloning);
      return data;
    },
    enabled: Boolean(projectId),
    refetchInterval: pollingEnabled ? 3000 : false,
  });

  const layersQuery = useQuery({
    queryKey: ["session-layers", sessionId],
    queryFn: () => listSessionLayers(sessionId!),
    enabled: Boolean(sessionId),
  });

  const removeSourceMut = useMutation({
    mutationFn: (sourceId: string) =>
      removeContextSource(projectId, sourceId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["context-sources", projectId],
      }),
  });

  const removeLayerMut = useMutation({
    mutationFn: (layerId: string) =>
      removeSessionLayer(sessionId!, layerId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["session-layers", sessionId],
      }),
  });

  const cloneMut = useMutation({
    mutationFn: (sourceId: string) => cloneRepoSource(sourceId),
    onSuccess: () => {
      setPollingEnabled(true);
      queryClient.invalidateQueries({ queryKey: ["context-sources", projectId] });
    },
  });

  const sources = sourcesQuery.data ?? [];
  const layers = layersQuery.data ?? [];

  return (
    <div className="flex flex-col rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)]">
      <div className="flex items-center gap-1 border-b border-[var(--o-border)] px-3">
        <button
          type="button"
          onClick={() => setTab("sources")}
          className={clsx(
            "px-3 py-2.5 text-xs font-medium transition-colors",
            tab === "sources"
              ? "border-b-2 border-[var(--o-accent)] text-[var(--o-text)]"
              : "text-[var(--o-text-secondary)] hover:text-[var(--o-text)]",
          )}
        >
          Sources ({sources.length})
        </button>
        {sessionId && (
          <button
            type="button"
            onClick={() => setTab("layers")}
            className={clsx(
              "px-3 py-2.5 text-xs font-medium transition-colors",
              tab === "layers"
                ? "border-b-2 border-[var(--o-accent)] text-[var(--o-text)]"
                : "text-[var(--o-text-secondary)] hover:text-[var(--o-text)]",
            )}
          >
            Layers ({layers.length})
          </button>
        )}
      </div>

      <div className="flex-1 overflow-auto p-3">
        {tab === "sources" && (
          <div className="space-y-2">
            {sourcesQuery.isLoading ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--o-text-secondary)]" />
              </div>
            ) : sources.length === 0 ? (
              <p className="py-6 text-center text-xs text-[var(--o-border-subtle)]">
                No context sources yet
              </p>
            ) : (
              sources.map((src) => {
                const Icon = SOURCE_ICONS[src.type] ?? Database;
                const isRepo = src.type === "github_repo" || src.type === "gitlab_repo";
                const cloneStatus = (src.config?.clone_status ?? null) as string | null;
                const isCloning = cloneStatus === "cloning";
                const isCloned = cloneStatus === "done";

                return (
                  <div
                    key={src.id}
                    className="rounded-md bg-[var(--o-bg)] px-3 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--o-text-secondary)]" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-[var(--o-text)]">
                          {src.name}
                        </p>
                        <p className="truncate text-[10px] text-[var(--o-border-subtle)]">
                          {SOURCE_TYPE_LABELS[src.type] ?? src.type}
                          {src.url ? ` • ${src.url}` : ""}
                        </p>
                      </div>
                      {isRepo && !isCloning && (
                        <button
                          type="button"
                          onClick={() => cloneMut.mutate(src.id)}
                          disabled={cloneMut.isPending}
                          title={isCloned ? "Re-clone" : "Clone repo"}
                          className={clsx(
                            "shrink-0 rounded p-1 transition-colors",
                            isCloned
                              ? "text-[var(--o-green)] hover:text-[var(--o-accent)]"
                              : "text-[var(--o-warning)] hover:text-[var(--o-accent)]",
                          )}
                        >
                          {isCloned ? (
                            <RefreshCw className="h-3 w-3" />
                          ) : (
                            <GitBranch className="h-3 w-3" />
                          )}
                        </button>
                      )}
                      {isCloning && (
                        <Loader2 className="h-3 w-3 shrink-0 animate-spin text-[var(--o-accent)]" />
                      )}
                      <button
                        type="button"
                        onClick={() => removeSourceMut.mutate(src.id)}
                        className="shrink-0 rounded p-1 text-[var(--o-border-subtle)] hover:text-[var(--o-danger)]"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>

                    {isCloned && (
                      <div className="mt-1 flex items-center gap-2 pl-5">
                        <Check className="h-2.5 w-2.5 text-[var(--o-green)]" />
                        <span className="text-[10px] text-[var(--o-green)]">
                          Cloned — AI explores on-demand via tools
                        </span>
                      </div>
                    )}

                    {isCloning && (
                      <div className="mt-1.5 pl-5">
                        <p className="text-[10px] text-[var(--o-accent)]">
                          Cloning repository…
                        </p>
                      </div>
                    )}

                    {cloneStatus === "error" && (
                      <div className="mt-1 pl-5">
                        <p className="text-[10px] text-[var(--o-danger)]">
                          {(src.config?.clone_error as string) || "Clone failed"}
                        </p>
                      </div>
                    )}
                  </div>
                );
              })
            )}
            <button
              type="button"
              onClick={() => setShowAddSource(true)}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-[var(--o-border)] py-2 text-xs text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-accent)]/40 hover:text-[var(--o-accent)]"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Source
            </button>
          </div>
        )}

        {tab === "layers" && sessionId && (
          <div className="space-y-2">
            {layersQuery.isLoading ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--o-text-secondary)]" />
              </div>
            ) : layers.length === 0 ? (
              <p className="py-6 text-center text-xs text-[var(--o-border-subtle)]">
                No context layers yet. Paste a PR URL, Jira ticket, or Google
                Doc to add one.
              </p>
            ) : (
              layers.map((layer) => {
                const Icon = SOURCE_ICONS[layer.type] ?? Layers;
                return (
                  <div
                    key={layer.id}
                    className="flex items-center gap-2 rounded-md bg-[var(--o-bg)] px-3 py-2"
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--o-text-secondary)]" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium text-[var(--o-text)]">
                        {layer.label}
                      </p>
                      <p className="truncate text-[10px] text-[var(--o-border-subtle)]">
                        {LAYER_TYPE_LABELS[layer.type] ?? layer.type}
                        {layer.token_count > 0
                          ? ` • ${layer.token_count.toLocaleString()} tokens`
                          : ""}
                      </p>
                    </div>
                    {layer.reference_url && (
                      <a
                        href={layer.reference_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="shrink-0 rounded p-1 text-[var(--o-border-subtle)] hover:text-[var(--o-accent)]"
                      >
                        <Link2 className="h-3 w-3" />
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={() => removeLayerMut.mutate(layer.id)}
                      className="shrink-0 rounded p-1 text-[var(--o-border-subtle)] hover:text-[var(--o-danger)]"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                );
              })
            )}
            <button
              type="button"
              onClick={() => setShowAddLayer(true)}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-[var(--o-border)] py-2 text-xs text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-accent)]/40 hover:text-[var(--o-accent)]"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Layer
            </button>
          </div>
        )}
      </div>

      {showAddSource && (
        <AddSourceModal
          projectId={projectId}
          onClose={() => setShowAddSource(false)}
        />
      )}
      {showAddLayer && sessionId && (
        <AddLayerModal
          sessionId={sessionId}
          onClose={() => setShowAddLayer(false)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add Source Modal
// ---------------------------------------------------------------------------

function AddSourceModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<ContextSourceType>("github_repo");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");

  const mut = useMutation({
    mutationFn: (input: AddContextSourceInput) =>
      addContextSource(projectId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["context-sources", projectId],
      });
      onClose();
    },
  });

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center o-modal-backdrop p-4"
      onClick={() => !mut.isPending && onClose()}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-md o-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--o-border)] px-5 py-4">
          <h2 className="text-lg font-semibold text-[var(--o-text)]">
            Add Context Source
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--o-text-secondary)] hover:text-[var(--o-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <form
          className="space-y-4 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            mut.mutate({
              type,
              name: name.trim(),
              url: url.trim() || undefined,
            });
          }}
        >
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Type
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as ContextSourceType)}
              className="w-full rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] outline-none"
            >
              {Object.entries(SOURCE_TYPE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] outline-none placeholder:text-[var(--o-border-subtle)] focus:border-[var(--o-accent)]"
              placeholder="e.g. odh-dashboard"
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              URL (optional)
            </label>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="w-full rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] outline-none placeholder:text-[var(--o-border-subtle)] focus:border-[var(--o-accent)]"
              placeholder="https://github.com/org/repo"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={mut.isPending}
              className="rounded-md px-3 py-2 text-sm text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || mut.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-[var(--o-green-bg)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--o-green-bg-hover)] disabled:opacity-50"
            >
              {mut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Add
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add Layer Modal
// ---------------------------------------------------------------------------

function AddLayerModal({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<SessionLayerType>("pull_request");
  const [label, setLabel] = useState("");
  const [refUrl, setRefUrl] = useState("");

  const mut = useMutation({
    mutationFn: (input: AddSessionLayerInput) =>
      addSessionLayer(sessionId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["session-layers", sessionId],
      });
      onClose();
    },
  });

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center o-modal-backdrop p-4"
      onClick={() => !mut.isPending && onClose()}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-md o-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--o-border)] px-5 py-4">
          <h2 className="text-lg font-semibold text-[var(--o-text)]">
            Add Context Layer
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--o-text-secondary)] hover:text-[var(--o-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <form
          className="space-y-4 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (!label.trim()) return;
            mut.mutate({
              type,
              label: label.trim(),
              reference_url: refUrl.trim() || undefined,
            });
          }}
        >
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Type
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as SessionLayerType)}
              className="w-full rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] outline-none"
            >
              {Object.entries(LAYER_TYPE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Label
            </label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="w-full rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] outline-none placeholder:text-[var(--o-border-subtle)] focus:border-[var(--o-accent)]"
              placeholder="e.g. PR #1234 - Fix auth flow"
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Reference URL (optional)
            </label>
            <input
              value={refUrl}
              onChange={(e) => setRefUrl(e.target.value)}
              className="w-full rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] outline-none placeholder:text-[var(--o-border-subtle)] focus:border-[var(--o-accent)]"
              placeholder="https://github.com/org/repo/pull/1234"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={mut.isPending}
              className="rounded-md px-3 py-2 text-sm text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!label.trim() || mut.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-[var(--o-green-bg)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--o-green-bg-hover)] disabled:opacity-50"
            >
              {mut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Add
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
