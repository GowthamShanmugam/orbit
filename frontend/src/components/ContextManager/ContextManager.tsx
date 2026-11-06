import {
  addContextSource,
  addSessionLayer,
  cloneRepoSource,
  listContextSources,
  listSessionLayers,
  removeContextSource,
  removeSessionLayer,
  retryPrLayerCheckout,
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
  Eye,
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

const REPO_STREAM_OPTIONS: {
  value: "" | "upstream" | "midstream" | "downstream";
  label: string;
}[] = [
  { value: "", label: "Stream (optional)" },
  { value: "upstream", label: "Upstream" },
  { value: "midstream", label: "Midstream" },
  { value: "downstream", label: "Downstream" },
];

const DEFAULT_REPO_BRANCH = "main";

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

export type PRProvider = "github" | "gitlab";

export interface PRLayerInfo {
  owner: string;
  repo: string;
  prNumber: number;
  label: string;
  url: string;
  provider: PRProvider;
  host?: string;
}

interface Props {
  projectId: string;
  sessionId?: string;
  readOnly?: boolean;
  onViewPR?: (info: PRLayerInfo) => void;
}

/** Parse GitHub PR or GitLab MR URLs for the in-app review viewer. */
export function parsePRUrl(url: string): Omit<PRLayerInfo, "label" | "url"> | null {
  const gh = url.match(/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/i);
  if (gh) {
    return {
      provider: "github",
      owner: gh[1],
      repo: gh[2],
      prNumber: parseInt(gh[3], 10),
      host: "github.com",
    };
  }
  const gl =
    url.match(/^https?:\/\/([^/]+)\/(.+?)\/-\/merge_requests\/(\d+)/i) ||
    url.match(/^https?:\/\/([^/]+)\/(.+?)\/merge_requests\/(\d+)/i);
  if (gl) {
    const host = gl[1];
    const fullPath = gl[2].replace(/\/+$/, "");
    const parts = fullPath.split("/").filter(Boolean);
    if (parts.length < 2) return null;
    return {
      provider: "gitlab",
      host,
      owner: parts.slice(0, -1).join("/"),
      repo: parts[parts.length - 1],
      prNumber: parseInt(gl[3], 10),
    };
  }
  return null;
}

export default function ContextManager({ projectId, sessionId, readOnly = false, onViewPR }: Props) {
  const queryClient = useQueryClient();
  const [showAddSource, setShowAddSource] = useState(false);
  const [showAddLayer, setShowAddLayer] = useState(false);
  const [pollingEnabled, setPollingEnabled] = useState(false);

  const sourcesQuery = useQuery({
    queryKey: ["context-sources", projectId],
    queryFn: async () => {
      const data = await listContextSources(projectId);
      const anyCloning = data.some((s) => s.config?.clone_status === "cloning");
      setPollingEnabled(anyCloning);
      return data;
    },
    enabled: Boolean(projectId),
    refetchInterval: pollingEnabled ? 1000 : false,
  });

  const layersQuery = useQuery({
    queryKey: ["session-layers", sessionId],
    queryFn: () => listSessionLayers(sessionId!),
    enabled: Boolean(sessionId),
    refetchInterval: (query) => {
      const rows = query.state.data ?? [];
      const fetching = rows.some(
        (l) =>
          l.type === "pull_request" &&
          l.cached_content?.pr_checkout_status === "fetching",
      );
      return fetching ? 1000 : false;
    },
  });

  const removeSourceMut = useMutation({
    mutationFn: (sourceId: string) => removeContextSource(projectId, sourceId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["context-sources", projectId],
      }),
  });

  const removeLayerMut = useMutation({
    mutationFn: (layerId: string) => removeSessionLayer(sessionId!, layerId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["session-layers", sessionId],
      }),
  });

  const retryCheckoutMut = useMutation({
    mutationFn: (layerId: string) => retryPrLayerCheckout(sessionId!, layerId),
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

  const isFullPage = !sessionId;

  if (isFullPage) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
              Context Sources
            </h2>
            <p className="mt-1 text-xs text-[var(--o-text-tertiary)]">
              Link repos, docs, and other references the AI can use across all sessions.
            </p>
          </div>
          {!readOnly && (
            <button
              type="button"
              onClick={() => setShowAddSource(true)}
              className="flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
            >
              <Plus className="h-4 w-4" />
              Add Source
            </button>
          )}
        </div>

      <div className="o-panel flex flex-col">
        <div className="flex items-center gap-1 border-b border-[var(--o-border)] px-3">
          <span className="o-tab o-tab-active text-xs font-medium">
            Sources ({sources.length})
          </span>
        </div>

        <div className="flex-1 overflow-auto p-3">
          <div className="space-y-2">
            <p className="mb-1 text-[11px] leading-relaxed text-[var(--o-text-tertiary)]">
              <span className="font-medium text-[var(--o-text-secondary)]">Sources</span>{" "}
              belong to this <span className="text-[var(--o-text-secondary)]">project</span>.
              Repos and links here are shared by every session—indexing, explorer, and
              tools—not only this chat.
            </p>

            {sourcesQuery.isLoading ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--o-text-secondary)]" />
              </div>
            ) : sources.length === 0 ? (
              <div className="py-5 text-center">
                <p className="text-xs font-medium text-[var(--o-text-secondary)]">
                  No context sources yet
                </p>
                <p className="mt-2 text-[11px] leading-relaxed text-[var(--o-text-tertiary)]">
                  Add a GitHub/GitLab repo or other link so Orbit can index and use it
                  across <span className="text-[var(--o-text-secondary)]">all sessions</span>{" "}
                  in this project.
                </p>
              </div>
            ) : (
              sources.map((src) => {
                const Icon = SOURCE_ICONS[src.type] ?? Database;
                const isRepo = src.type === "github_repo" || src.type === "gitlab_repo";
                const cloneStatus = (src.config?.clone_status ?? null) as string | null;
                const isCloning = cloneStatus === "cloning";
                const isCloned = cloneStatus === "done";
                const clonePct = Number(src.config?.clone_progress ?? 0);
                const cloneStage = String(src.config?.clone_stage || "");

                return (
                  <div key={src.id} className="rounded-md bg-[var(--o-bg)] px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--o-text-secondary)]" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-[var(--o-text)]">
                          {src.name}
                        </p>
                        <p className="break-all text-[10px] leading-snug text-[var(--o-text-secondary)]">
                          <span className="text-[var(--o-text-tertiary)]">
                            {SOURCE_TYPE_LABELS[src.type] ?? src.type}
                          </span>
                          {src.url ? (
                            <>
                              {" · "}
                              <span className="font-mono text-[var(--o-accent)]">{src.url}</span>
                            </>
                          ) : null}
                        </p>
                      </div>
                      {isRepo && !readOnly && (
                        <button
                          type="button"
                          onClick={() => cloneMut.mutate(src.id)}
                          disabled={cloneMut.isPending}
                          title={
                            isCloning
                              ? "Cancel and retry clone"
                              : isCloned
                                ? "Re-clone"
                                : "Clone repo"
                          }
                          className={clsx(
                            "shrink-0 rounded p-1 transition-colors",
                            isCloning
                              ? "text-[var(--o-accent)] hover:text-[var(--o-accent-hover)]"
                              : isCloned
                                ? "text-[var(--o-green)] hover:text-[var(--o-accent)]"
                                : "text-[var(--o-warning)] hover:text-[var(--o-accent)]",
                          )}
                        >
                          {isCloning || isCloned ? (
                            <RefreshCw
                              className={clsx(
                                "h-3 w-3",
                                (isCloning || cloneMut.isPending) && "animate-spin",
                              )}
                            />
                          ) : (
                            <GitBranch className="h-3 w-3" />
                          )}
                        </button>
                      )}
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={() => removeSourceMut.mutate(src.id)}
                          className="shrink-0 rounded p-1 text-[var(--o-text-tertiary)] hover:text-[var(--o-danger)]"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      )}
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
                      <div className="mt-1.5 space-y-1 pl-5">
                        <p className="text-[10px] text-[var(--o-accent)]">
                          {Math.max(0, Math.min(100, clonePct))}%
                          {cloneStage ? ` · ${cloneStage}` : " · Cloning…"}
                        </p>
                        <div className="h-1 overflow-hidden rounded-full bg-[var(--o-bg-subtle)]">
                          <div
                            className="h-full rounded-full bg-[var(--o-accent)] transition-[width] duration-300"
                            style={{
                              width: `${Math.max(2, Math.min(100, clonePct))}%`,
                            }}
                          />
                        </div>
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

          </div>
        </div>

        {showAddSource && !readOnly && (
          <AddSourceModal projectId={projectId} onClose={() => setShowAddSource(false)} />
        )}
      </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <div className="flex-1 overflow-auto p-3 space-y-4">
        <section>
          <div className="mb-1.5">
            <div className="flex items-center justify-between">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
                Context Sources
              </h3>
              {!readOnly && (
                <button
                  type="button"
                  onClick={() => setShowAddSource(true)}
                  className="rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)]"
                  title="Add source"
                >
                  <Plus className="h-3 w-3" />
                </button>
              )}
            </div>
            <p className="mt-0.5 text-[9px] leading-snug text-[var(--o-text-tertiary)]">
              Repos and docs shared across all sessions in this project.
            </p>
          </div>
          {sourcesQuery.isLoading ? (
            <div className="flex justify-center py-4">
              <Loader2 className="h-4 w-4 animate-spin text-[var(--o-text-secondary)]" />
            </div>
          ) : sources.length === 0 ? (
            <p className="py-2 text-center text-[11px] text-[var(--o-text-tertiary)]">
              No sources yet
            </p>
          ) : (
            <div className="space-y-1">
              {sources.map((src) => {
                const Icon = SOURCE_ICONS[src.type] ?? Database;
                const isRepo = src.type === "github_repo" || src.type === "gitlab_repo";
                const cloneStatus = (src.config?.clone_status ?? null) as string | null;
                const isCloning = cloneStatus === "cloning";
                const isCloned = cloneStatus === "done";
                const clonePct = Number(src.config?.clone_progress ?? 0);
                const cloneStage = String(src.config?.clone_stage || "");

                return (
                  <div key={src.id} className="group rounded-md bg-[var(--o-bg)] px-2.5 py-1.5">
                    <div className="flex items-center gap-2">
                      <Icon className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
                      <p className="min-w-0 flex-1 truncate text-xs text-[var(--o-text)]">{src.name}</p>
                      {isRepo && !readOnly && (
                        <button
                          type="button"
                          onClick={() => cloneMut.mutate(src.id)}
                          disabled={cloneMut.isPending}
                          title={
                            isCloning
                              ? "Cancel and retry clone"
                              : isCloned
                                ? "Re-clone"
                                : "Clone repo"
                          }
                          className={clsx(
                            "shrink-0 rounded p-0.5 transition-colors",
                            isCloning
                              ? "text-[var(--o-accent)] hover:text-[var(--o-accent-hover)]"
                              : isCloned
                                ? "text-[var(--o-green)] hover:text-[var(--o-accent)]"
                                : "text-[var(--o-warning)] hover:text-[var(--o-accent)]",
                          )}
                        >
                          {isCloning || isCloned ? (
                            <RefreshCw
                              className={clsx(
                                "h-2.5 w-2.5",
                                (isCloning || cloneMut.isPending) && "animate-spin",
                              )}
                            />
                          ) : (
                            <GitBranch className="h-2.5 w-2.5" />
                          )}
                        </button>
                      )}
                      {!readOnly && (
                        <button
                          type="button"
                          onClick={() => removeSourceMut.mutate(src.id)}
                          className="shrink-0 rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-danger)]"
                        >
                          <Trash2 className="h-2.5 w-2.5" />
                        </button>
                      )}
                    </div>
                    {isCloned && (
                      <div className="mt-0.5 flex items-center gap-1 pl-5">
                        <Check className="h-2 w-2 text-[var(--o-green)]" />
                        <span className="text-[9px] text-[var(--o-green)]">Cloned</span>
                      </div>
                    )}
                    {isCloning && (
                      <div className="mt-0.5 space-y-1 pl-5">
                        <p className="text-[9px] text-[var(--o-accent)]">
                          {Math.max(0, Math.min(100, clonePct))}%
                          {cloneStage ? ` · ${cloneStage}` : ""}
                        </p>
                        <div className="h-1 overflow-hidden rounded-full bg-[var(--o-bg-subtle)]">
                          <div
                            className="h-full rounded-full bg-[var(--o-accent)] transition-[width] duration-300"
                            style={{
                              width: `${Math.max(2, Math.min(100, clonePct))}%`,
                            }}
                          />
                        </div>
                      </div>
                    )}
                    {cloneStatus === "error" && (
                      <p className="mt-0.5 pl-5 text-[9px] text-[var(--o-danger)]">
                        {(src.config?.clone_error as string) || "Clone failed"}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Layers — session-level */}
        {sessionId && (
          <section>
            <div className="mb-1.5">
              <div className="flex items-center justify-between">
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
                  Session Layers
                </h3>
                {!readOnly && (
                  <button
                    type="button"
                    onClick={() => setShowAddLayer(true)}
                    className="rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)]"
                    title="Add layer"
                  >
                    <Plus className="h-3 w-3" />
                  </button>
                )}
              </div>
              <p className="mt-0.5 text-[9px] leading-snug text-[var(--o-text-tertiary)]">
                Extra context for this session only — PRs, files, or URLs.
              </p>
            </div>
            {layersQuery.isLoading ? (
              <div className="flex justify-center py-4">
                <Loader2 className="h-4 w-4 animate-spin text-[var(--o-text-secondary)]" />
              </div>
            ) : layers.length === 0 ? (
              <p className="py-2 text-center text-[11px] text-[var(--o-text-tertiary)]">
                No layers yet
              </p>
            ) : (
              <div className="space-y-1">
                {layers.map((layer) => {
                  const Icon = SOURCE_ICONS[layer.type] ?? Layers;
                  const prUrl =
                    layer.type === "pull_request"
                      ? layer.reference_url ||
                        (parsePRUrl(layer.label) ? layer.label : null)
                      : null;
                  const prInfo = prUrl ? parsePRUrl(prUrl) : null;
                  const checkoutStatus =
                    layer.type === "pull_request"
                      ? String(layer.cached_content?.pr_checkout_status || "")
                      : "";
                  const checkoutPct = Number(layer.cached_content?.pr_checkout_progress ?? 0);
                  const checkoutStage = String(
                    layer.cached_content?.pr_checkout_stage || "",
                  );
                  const checkoutSha = String(
                    (layer.cached_content?.pr_checkout as { sha?: string } | undefined)?.sha ||
                      "",
                  );
                  const checkoutError = String(
                    layer.cached_content?.pr_checkout_error || "",
                  );
                  const openInApp =
                    prInfo && onViewPR
                      ? () =>
                          onViewPR({
                            ...prInfo,
                            label: layer.label,
                            url: prUrl!,
                          })
                      : null;
                  return (
                    <div key={layer.id} className="group rounded-md bg-[var(--o-bg)] px-2.5 py-1.5">
                      <div className="flex items-center gap-2">
                        <Icon className="h-3 w-3 shrink-0 text-[var(--o-text-secondary)]" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs text-[var(--o-text)]">{layer.label}</p>
                          <p className="truncate text-[9px] text-[var(--o-text-tertiary)]">
                            {LAYER_TYPE_LABELS[layer.type] ?? layer.type}
                            {layer.token_count > 0
                              ? ` · ${layer.token_count.toLocaleString()} tok`
                              : ""}
                          </p>
                          {layer.type === "pull_request" && checkoutStatus === "fetching" && (
                            <div className="mt-1 space-y-1">
                              <p className="flex items-center gap-1 text-[9px] text-[var(--o-accent)]">
                                <Loader2 className="h-2.5 w-2.5 animate-spin" />
                                {Math.max(0, Math.min(100, checkoutPct))}%
                                {checkoutStage ? ` · ${checkoutStage}` : ""}
                              </p>
                              <div className="h-1 overflow-hidden rounded-full bg-[var(--o-bg-subtle)]">
                                <div
                                  className="h-full rounded-full bg-[var(--o-accent)] transition-[width] duration-300"
                                  style={{
                                    width: `${Math.max(2, Math.min(100, checkoutPct))}%`,
                                  }}
                                />
                              </div>
                            </div>
                          )}
                          {layer.type === "pull_request" && checkoutStatus === "ready" && (
                            <p className="mt-0.5 text-[9px] text-[var(--o-success,var(--o-accent))]">
                              Ready{checkoutSha ? ` · ${checkoutSha.slice(0, 8)}` : ""}
                            </p>
                          )}
                          {layer.type === "pull_request" && checkoutStatus === "error" && (
                            <p
                              className="mt-0.5 truncate text-[9px] text-[var(--o-danger)]"
                              title={checkoutError || "Checkout failed"}
                            >
                              Fetch failed
                            </p>
                          )}
                        </div>
                        {layer.type === "pull_request" && !readOnly && (
                          <button
                            type="button"
                            onClick={() => retryCheckoutMut.mutate(layer.id)}
                            disabled={retryCheckoutMut.isPending}
                            title="Retry / refresh PR head checkout"
                            className="shrink-0 rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)] disabled:opacity-40"
                          >
                            <RefreshCw
                              className={clsx(
                                "h-3 w-3",
                                (retryCheckoutMut.isPending ||
                                  checkoutStatus === "fetching") &&
                                  "animate-spin",
                              )}
                            />
                          </button>
                        )}
                        {openInApp && (
                          <button
                            type="button"
                            onClick={openInApp}
                            title="Open in Orbit review"
                            className="shrink-0 rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)]"
                          >
                            <Eye className="h-3 w-3" />
                          </button>
                        )}
                        {openInApp ? (
                          <button
                            type="button"
                            onClick={openInApp}
                            title="Open in Orbit review"
                            className="shrink-0 rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)]"
                          >
                            <Link2 className="h-2.5 w-2.5" />
                          </button>
                        ) : prUrl ? (
                          <a
                            href={prUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="Open external link"
                            className="shrink-0 rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)]"
                          >
                            <Link2 className="h-2.5 w-2.5" />
                          </a>
                        ) : layer.reference_url ? (
                          <a
                            href={layer.reference_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="Open external link"
                            className="shrink-0 rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)]"
                          >
                            <Link2 className="h-2.5 w-2.5" />
                          </a>
                        ) : null}
                        {!readOnly && (
                          <button
                            type="button"
                            onClick={() => removeLayerMut.mutate(layer.id)}
                            className="shrink-0 rounded p-0.5 text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-danger)]"
                          >
                            <Trash2 className="h-2.5 w-2.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        )}
      </div>

      {showAddSource && !readOnly && (
        <AddSourceModal projectId={projectId} onClose={() => setShowAddSource(false)} />
      )}
      {showAddLayer && sessionId && !readOnly && (
        <AddLayerModal sessionId={sessionId} onClose={() => setShowAddLayer(false)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add Source Modal
// ---------------------------------------------------------------------------

function AddSourceModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<ContextSourceType>("github_repo");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState(DEFAULT_REPO_BRANCH);
  const [repoStream, setRepoStream] = useState<"" | "upstream" | "midstream" | "downstream">("");

  const mut = useMutation({
    mutationFn: (input: AddContextSourceInput) => addContextSource(projectId, input),
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
          <h2 className="text-lg font-semibold text-[var(--o-text)]">Add Context Source</h2>
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
            const base: AddContextSourceInput = {
              type,
              name: name.trim(),
              url: url.trim() || undefined,
            };
            if (type === "github_repo" || type === "gitlab_repo") {
              const cfg: Record<string, unknown> = {
                branch: branch.trim() || DEFAULT_REPO_BRANCH,
              };
              if (repoStream) cfg.repo_stream = repoStream;
              base.config = cfg;
            }
            mut.mutate(base);
          }}
        >
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Type
            </label>
            <select
              value={type}
              onChange={(e) => {
                setType(e.target.value as ContextSourceType);
                setBranch(DEFAULT_REPO_BRANCH);
                setRepoStream("");
              }}
              className="o-input w-full px-3 py-2 text-sm"
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
              className="o-input w-full px-3 py-2 text-sm"
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
              className="o-input w-full px-3 py-2 text-sm"
              placeholder="https://github.com/org/repo"
            />
          </div>
          {(type === "github_repo" || type === "gitlab_repo") && (
            <>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                  Branch
                </label>
                <input
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className="o-input w-full px-3 py-2 text-sm"
                  placeholder={DEFAULT_REPO_BRANCH}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                  Repo stream
                </label>
                <select
                  value={repoStream}
                  onChange={(e) =>
                    setRepoStream(e.target.value as "" | "upstream" | "midstream" | "downstream")
                  }
                  className="o-input w-full px-3 py-2 text-sm"
                >
                  {REPO_STREAM_OPTIONS.map((opt) => (
                    <option key={opt.value || "none"} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={mut.isPending}
              className="o-btn-ghost px-3 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || mut.isPending}
              className="o-btn-success inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
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

function AddLayerModal({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<SessionLayerType>("pull_request");
  const [label, setLabel] = useState("");
  const [refUrl, setRefUrl] = useState("");
  const [notes, setNotes] = useState("");

  const mut = useMutation({
    mutationFn: (input: AddSessionLayerInput) => addSessionLayer(sessionId, input),
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
          <h2 className="text-lg font-semibold text-[var(--o-text)]">Add Context Layer</h2>
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
            const n = notes.trim();
            mut.mutate({
              type,
              label: label.trim(),
              reference_url: refUrl.trim() || undefined,
              ...(n ? { cached_content: { text: n } } : {}),
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
              className="o-input w-full px-3 py-2 text-sm"
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
              className="o-input w-full px-3 py-2 text-sm"
              placeholder={
                type === "pull_request"
                  ? "PR title, or paste the full PR/MR URL here"
                  : "e.g. PR #1234 - Fix auth flow"
              }
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Reference URL {type === "pull_request" ? "(or paste URL in Label)" : "(optional)"}
            </label>
            <input
              value={refUrl}
              onChange={(e) => setRefUrl(e.target.value)}
              className="o-input w-full px-3 py-2 text-sm"
              placeholder={
                type === "jira_ticket"
                  ? "https://your-org.atlassian.net/browse/PROJ-123"
                  : type === "pull_request"
                    ? "https://github.com/org/repo/pull/1234 or GitLab …/-/merge_requests/123"
                    : "https://…"
              }
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Notes (optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              className="o-input w-full resize-y px-3 py-2 text-sm"
              placeholder="Paste issue/PR description, acceptance criteria, or any text to include in every message in this session."
            />
            <p className="mt-1 text-[11px] text-[var(--o-text-tertiary)]">
              Without notes, the model still sees your label and URL; add notes for full context
              without using MCP.
            </p>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={mut.isPending}
              className="o-btn-ghost px-3 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!label.trim() || mut.isPending}
              className="o-btn-success inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
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
