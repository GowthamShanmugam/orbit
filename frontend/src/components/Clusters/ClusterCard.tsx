import { deleteCluster, testConnection } from "@/api/clusters";
import type { ProjectCluster } from "@/types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity,
  CheckCircle2,
  Loader2,
  PlugZap,
  Server,
  Trash2,
  XCircle,
} from "lucide-react";

const STATUS_STYLES: Record<
  string,
  { dot: string; label: string; icon: typeof CheckCircle2 }
> = {
  connected: {
    dot: "bg-[var(--o-green)]",
    label: "text-[var(--o-green)]",
    icon: CheckCircle2,
  },
  error: { dot: "bg-[var(--o-danger)]", label: "text-[var(--o-danger)]", icon: XCircle },
  syncing: {
    dot: "bg-[var(--o-warning)]",
    label: "text-[var(--o-warning)]",
    icon: Activity,
  },
  pending: {
    dot: "bg-[var(--o-text-secondary)]",
    label: "text-[var(--o-text-secondary)]",
    icon: Activity,
  },
};

interface Props {
  cluster: ProjectCluster;
  projectId: string;
}

export default function ClusterCard({ cluster, projectId }: Props) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["clusters", projectId] });

  const testMut = useMutation({
    mutationFn: () => testConnection(projectId, cluster.id),
    onSettled: invalidate,
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteCluster(projectId, cluster.id),
    onSettled: invalidate,
  });

  const st = STATUS_STYLES[cluster.status] ?? STATUS_STYLES.pending;
  const StatusIcon = st.icon;

  return (
    <div className="o-card-hover rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-4" style={{ backgroundImage: "var(--o-gradient-card)" }}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--o-bg-subtle)]">
            <Server className="h-4 w-4 text-[var(--o-accent)]" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-medium text-[var(--o-text)]">
              {cluster.name}
            </h3>
            <p className="truncate text-xs text-[var(--o-border-subtle)]">
              {cluster.api_server_url || "No API server URL"}
            </p>
          </div>
        </div>

        <span
          className={clsx(
            "o-badge shrink-0",
            cluster.role === "context" ? "o-badge-accent" : "o-badge-warning"
          )}
        >
          {cluster.role}
        </span>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <div className={clsx("h-2 w-2 rounded-full", st.dot)} />
        <span className={clsx("text-xs font-medium", st.label)}>
          <StatusIcon className="mr-1 inline-block h-3 w-3" />
          {cluster.status}
        </span>
        {cluster.status_message && (
          <span className="truncate text-xs text-[var(--o-border-subtle)]">
            — {cluster.status_message}
          </span>
        )}
      </div>

      {cluster.namespace_filter && cluster.namespace_filter.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {cluster.namespace_filter.map((ns) => (
            <span
              key={ns}
              className="rounded bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[10px] text-[var(--o-text-secondary)]"
            >
              {ns}
            </span>
          ))}
        </div>
      )}

      <p className="mt-2 text-[11px] text-[var(--o-border-subtle)]">
        {cluster.role === "context"
          ? "AI queries this cluster on-demand for pods, logs, events, CRDs"
          : "AI can run commands, apply manifests, and run tests on this cluster"}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--o-border)] pt-3">
        <button
          type="button"
          onClick={() => testMut.mutate()}
          disabled={testMut.isPending}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-2.5 py-1.5 text-xs font-medium text-[var(--o-text)] transition-colors hover:border-[var(--o-accent)]/40 disabled:opacity-50"
        >
          {testMut.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <PlugZap className="h-3 w-3" />
          )}
          Test Connection
        </button>

        <div className="flex-1" />

        <button
          type="button"
          onClick={() => {
            if (confirm(`Delete cluster "${cluster.name}"?`)) {
              deleteMut.mutate();
            }
          }}
          disabled={deleteMut.isPending}
          className="rounded p-1.5 text-[var(--o-border-subtle)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-danger)]"
          title="Delete cluster"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {testMut.data && (
        <div
          className={clsx(
            "mt-2 rounded-md px-3 py-2 text-xs",
            testMut.data.connected
              ? "border border-[var(--o-green-bg)]/30 bg-[var(--o-green-bg)]/10 text-[var(--o-green)]"
              : "border border-[var(--o-danger)]/30 bg-[var(--o-danger)]/10 text-[var(--o-danger)]"
          )}
        >
          {testMut.data.message}
        </div>
      )}
    </div>
  );
}
