import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, Loader2, Server, Check, Database } from "lucide-react";
import clsx from "clsx";
import { suggestMappings, saveMappings } from "@/api/systemMap";
import { listContextSources } from "@/api/context";
import type { CreateMappingInput, ContextSource, MappingSuggestion } from "@/types";

interface Props {
  projectId: string;
  onComplete: () => void;
}

interface MappingRow {
  deploymentName: string;
  deploymentNamespace: string;
  clusterId: string;
  contextSourceId: string | null;
  isInfrastructure: boolean;
  confidence?: string;
  reason?: string;
}

export default function SetupWizard({ projectId, onComplete }: Props) {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<MappingRow[]>([]);
  const [discovered, setDiscovered] = useState(false);

  const sourcesQuery = useQuery({
    queryKey: ["context-sources", projectId],
    queryFn: () => listContextSources(projectId),
  });

  const repoSources = (sourcesQuery.data ?? []).filter(
    (s: ContextSource) => s.type === "github_repo" || s.type === "gitlab_repo",
  );

  const discoverMut = useMutation({
    mutationFn: () => suggestMappings(projectId),
    onSuccess: (suggestions: MappingSuggestion[]) => {
      setRows(
        suggestions.map((s) => ({
          deploymentName: s.deployment_name,
          deploymentNamespace: s.deployment_namespace,
          clusterId: s.cluster_id ?? "",
          contextSourceId: s.context_source_id,
          isInfrastructure: s.is_infrastructure,
          confidence: s.confidence,
          reason: s.reason,
        })),
      );
      setDiscovered(true);
    },
  });

  const saveMut = useMutation({
    mutationFn: (mappings: CreateMappingInput[]) => saveMappings(projectId, mappings),
    onSuccess: (data) => {
      queryClient.setQueryData(["system-map-mappings", projectId], data);
      onComplete();
    },
  });

  const handleSave = () => {
    const mappings: CreateMappingInput[] = rows.map((r) => ({
      cluster_id: r.clusterId,
      deployment_name: r.deploymentName,
      deployment_namespace: r.deploymentNamespace,
      context_source_id: r.isInfrastructure ? null : r.contextSourceId,
      is_infrastructure: r.isInfrastructure,
    }));
    saveMut.mutate(mappings);
  };

  if (!discovered) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--o-accent-muted)]">
          <Sparkles className="h-7 w-7 text-[var(--o-accent)]" />
        </div>
        <h3 className="mt-4 text-base font-semibold">Set up your System Map</h3>
        <p className="mt-2 max-w-md text-center text-sm text-[var(--o-text-secondary)]">
          Orbit will scan your cluster, find deployments related to your project's repos, and suggest
          which deployment maps to which repository.
        </p>
        <button
          type="button"
          className="o-btn-primary mt-6 flex items-center gap-2 text-sm"
          onClick={() => discoverMut.mutate()}
          disabled={discoverMut.isPending}
        >
          {discoverMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {discoverMut.isPending ? "Scanning cluster & matching..." : "Discover Services"}
        </button>
        {discoverMut.isError && (
          <p className="mt-3 text-xs text-[var(--o-danger)]">
            Failed to discover services. Make sure your cluster is connected.
          </p>
        )}
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="o-empty py-16 text-center">
        <Server className="mx-auto mb-3 h-8 w-8 text-[var(--o-text-secondary)]" />
        <p className="mb-1 text-sm font-medium">No matching deployments found</p>
        <p className="text-xs text-[var(--o-text-secondary)]">
          No deployments in your cluster could be matched to your project's repositories. Make sure
          repos are added as context sources and the cluster is connected.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--o-text-secondary)]">
            Review Mappings
          </h3>
          <p className="mt-1 text-xs text-[var(--o-text-secondary)]">
            {rows.length} deployments matched to your project repos. Adjust if needed, then confirm.
          </p>
        </div>
        <button
          type="button"
          className="o-btn-ghost flex items-center gap-1.5 text-xs"
          onClick={() => {
            setDiscovered(false);
            setRows([]);
          }}
        >
          Re-scan
        </button>
      </div>

      <div className="rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)]">
        <div className="grid grid-cols-[1fr_1fr_auto] gap-3 border-b border-[var(--o-border)] px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-[var(--o-text-secondary)]">
          <span>Deployment</span>
          <span>Repository</span>
          <span className="w-20 text-center">Infra</span>
        </div>

        <div className="divide-y divide-[var(--o-border)]">
          {rows.map((row, idx) => (
            <div
              key={`${row.deploymentName}-${row.deploymentNamespace}`}
              className="grid grid-cols-[1fr_1fr_auto] items-center gap-3 px-4 py-3"
            >
              <div className="flex items-center gap-2.5">
                <div
                  className={clsx(
                    "flex h-7 w-7 items-center justify-center rounded-lg",
                    row.isInfrastructure
                      ? "bg-[var(--o-text-secondary)]/10"
                      : "bg-[var(--o-accent-muted)]",
                  )}
                >
                  {row.isInfrastructure ? (
                    <Database className="h-3.5 w-3.5 text-[var(--o-text-secondary)]" />
                  ) : (
                    <Server className="h-3.5 w-3.5 text-[var(--o-accent)]" />
                  )}
                </div>
                <div>
                  <p className="text-sm font-medium">{row.deploymentName}</p>
                  <p className="text-xs text-[var(--o-text-secondary)]">
                    {row.deploymentNamespace}
                  </p>
                </div>
              </div>

              <div>
                {row.isInfrastructure ? (
                  <span className="text-xs italic text-[var(--o-text-secondary)]">
                    No repo (infrastructure)
                  </span>
                ) : (
                  <div className="flex items-center gap-2">
                    <select
                      className="o-input w-full text-sm"
                      value={row.contextSourceId ?? ""}
                      onChange={(e) => {
                        const val = e.target.value || null;
                        setRows((prev) =>
                          prev.map((r, i) => (i === idx ? { ...r, contextSourceId: val } : r)),
                        );
                      }}
                    >
                      <option value="">-- Select repo --</option>
                      {repoSources.map((s: ContextSource) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                    {row.confidence && (
                      <span
                        className={clsx(
                          "o-badge shrink-0 text-[10px]",
                          row.confidence === "high" && "bg-green-500/10 text-green-400",
                          row.confidence === "medium" && "bg-yellow-500/10 text-yellow-400",
                          row.confidence === "low" && "bg-red-500/10 text-red-400",
                        )}
                        title={row.reason}
                      >
                        {row.confidence}
                      </span>
                    )}
                  </div>
                )}
              </div>

              <div className="flex w-20 justify-center">
                <button
                  type="button"
                  className={clsx(
                    "flex h-6 w-6 items-center justify-center rounded-md border transition-colors",
                    row.isInfrastructure
                      ? "border-[var(--o-accent)] bg-[var(--o-accent)] text-white"
                      : "border-[var(--o-border)] hover:border-[var(--o-text-secondary)]",
                  )}
                  onClick={() =>
                    setRows((prev) =>
                      prev.map((r, i) =>
                        i === idx ? { ...r, isInfrastructure: !r.isInfrastructure } : r,
                      ),
                    )
                  }
                >
                  {row.isInfrastructure && <Check className="h-3.5 w-3.5" />}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--o-text-secondary)]">
          {rows.filter((r) => r.contextSourceId || r.isInfrastructure).length} of {rows.length}{" "}
          deployments mapped
        </p>
        <button
          type="button"
          className="o-btn-primary text-sm"
          onClick={handleSave}
          disabled={saveMut.isPending}
        >
          {saveMut.isPending ? (
            <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
          ) : null}
          Confirm &amp; Build Map
        </button>
      </div>
    </div>
  );
}
