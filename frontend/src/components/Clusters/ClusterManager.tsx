import { listClusters } from "@/api/clusters";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Plus, Server } from "lucide-react";
import { useState } from "react";
import type { ProjectCluster } from "@/types";
import AddClusterModal from "./AddClusterModal";
import ClusterCard from "./ClusterCard";
import EditClusterModal from "./EditClusterModal";

interface Props {
  projectId: string;
  /** When true, hide add / edit / test / delete cluster controls. */
  readOnly?: boolean;
}

export default function ClusterManager({ projectId, readOnly = false }: Props) {
  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<ProjectCluster | null>(null);

  const clustersQuery = useQuery({
    queryKey: ["clusters", projectId],
    queryFn: () => listClusters(projectId),
  });

  const clusters = clustersQuery.data ?? [];
  const contextClusters = clusters.filter((c) => c.role === "context");
  const testClusters = clusters.filter((c) => c.role === "test");

  if (clustersQuery.isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--o-text-secondary)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Server className="h-4 w-4 text-[var(--o-accent)]" />
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]">
            Live Clusters
          </h2>
          <span className="rounded-full bg-[var(--o-bg-subtle)] px-2 py-0.5 text-[10px] font-medium text-[var(--o-text-secondary)]">
            {clusters.length}
          </span>
        </div>
        {!readOnly && (
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="o-btn-primary inline-flex items-center gap-2 px-3 py-2 text-sm"
          >
            <Plus className="h-4 w-4" />
            Add Cluster
          </button>
        )}
      </div>

      {clusters.length === 0 ? (
        <div className="o-empty">
          <Server className="mx-auto mb-3 h-8 w-8 text-[var(--o-text-tertiary)]" />
          <p className="text-sm text-[var(--o-text-secondary)]">
            No clusters attached. Add a context cluster for AI queries or a test
            cluster for running e2e tests — the AI will use them on-demand via chat.
          </p>
          {!readOnly && (
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="o-btn-success mt-4 inline-flex items-center gap-2 px-4 py-2 text-sm"
            >
              <Plus className="h-4 w-4" />
              Add Your First Cluster
            </button>
          )}
        </div>
      ) : (
        <>
          {contextClusters.length > 0 && (
            <div>
              <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--o-accent)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--o-accent)]" />
                Context Clusters
                <span className="font-normal normal-case text-[var(--o-text-secondary)]">
                  — read-only, AI queries on-demand
                </span>
              </h3>
              <div className="grid gap-3 sm:grid-cols-2">
                {contextClusters.map((c) => (
                  <ClusterCard
                    key={c.id}
                    cluster={c}
                    projectId={projectId}
                    readOnly={readOnly}
                    onEdit={() => setEditing(c)}
                  />
                ))}
              </div>
            </div>
          )}

          {testClusters.length > 0 && (
            <div>
              <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--o-warning)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--o-warning)]" />
                Test Clusters
                <span className="font-normal normal-case text-[var(--o-text-secondary)]">
                  — read-write, AI runs tests via chat
                </span>
              </h3>
              <div className="grid gap-3 sm:grid-cols-2">
                {testClusters.map((c) => (
                  <ClusterCard
                    key={c.id}
                    cluster={c}
                    projectId={projectId}
                    readOnly={readOnly}
                    onEdit={() => setEditing(c)}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {addOpen && !readOnly && (
        <AddClusterModal
          projectId={projectId}
          onClose={() => setAddOpen(false)}
        />
      )}
      {editing && !readOnly && (
        <EditClusterModal
          projectId={projectId}
          cluster={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
