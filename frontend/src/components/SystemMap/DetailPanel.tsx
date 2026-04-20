import {
  X,
  Server,
  GitBranch,
  ExternalLink,
  MessageCircle,
  Database,
  Activity,
  AlertTriangle,
  Terminal,
  Loader2,
  RefreshCw,
  Box,
} from "lucide-react";
import clsx from "clsx";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { getServiceDetail, createDebugSession } from "@/api/systemMap";
import type { ServiceMappingResponse, MapStatusItem } from "@/types";

interface Props {
  projectId: string;
  mapping: ServiceMappingResponse;
  statusItem: MapStatusItem | undefined;
  onClose: () => void;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  healthy: { label: "Healthy", color: "text-green-400" },
  degraded: { label: "Degraded", color: "text-yellow-400" },
  failing: { label: "Failing", color: "text-red-400" },
};

export default function DetailPanel({ projectId, mapping, statusItem, onClose }: Props) {
  const navigate = useNavigate();
  const dep = statusItem?.deployment;
  const gap = statusItem?.gap;
  const statusInfo = STATUS_LABELS[dep?.status ?? ""] ?? {
    label: "Unknown",
    color: "text-gray-400",
  };

  const detailQuery = useQuery({
    queryKey: ["service-detail", projectId, mapping.id],
    queryFn: () => getServiceDetail(projectId, mapping.id),
    staleTime: 15_000,
  });

  const debugMut = useMutation({
    mutationFn: (prompt: string) => createDebugSession(projectId, mapping.id, prompt),
    onSuccess: ({ session_id }) => {
      navigate(`/projects/${projectId}/sessions/${session_id}?prompt=${encodeURIComponent(
        `Help me debug the ${mapping.deployment_name} service in namespace ${mapping.deployment_namespace}. Check its pod status, recent logs, and events.`,
      )}`);
    },
  });

  const detail = detailQuery.data;

  return (
    <div className="absolute right-0 top-0 z-20 flex h-full w-[380px] flex-col border-l border-[var(--o-border)] bg-[var(--o-bg)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--o-border)] px-4 py-3">
        <div className="flex items-center gap-2">
          <div
            className={clsx(
              "flex h-7 w-7 items-center justify-center rounded-lg",
              mapping.is_infrastructure
                ? "bg-[var(--o-text-secondary)]/10"
                : "bg-[var(--o-accent-muted)]",
            )}
          >
            {mapping.is_infrastructure ? (
              <Database className="h-3.5 w-3.5 text-[var(--o-text-secondary)]" />
            ) : (
              <Server className="h-3.5 w-3.5 text-[var(--o-accent)]" />
            )}
          </div>
          <div>
            <h3 className="text-sm font-semibold">{mapping.deployment_name}</h3>
            <p className="text-[10px] text-[var(--o-text-secondary)]">
              {mapping.deployment_namespace}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => detailQuery.refetch()}
            className="o-btn-ghost p-1"
            title="Refresh"
          >
            <RefreshCw className={clsx("h-3.5 w-3.5", detailQuery.isFetching && "animate-spin")} />
          </button>
          <button type="button" onClick={onClose} className="o-btn-ghost p-1">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {/* Status */}
        <section>
          <SectionHead icon={Activity} title="Status" />
          <div className="rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-3 text-sm">
            <div className="flex items-center justify-between">
              <span>Health</span>
              <span className={clsx("font-medium", statusInfo.color)}>{statusInfo.label}</span>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span>Pods</span>
              <span className="font-mono text-xs">
                {dep?.ready_replicas ?? 0}/{dep?.replicas ?? 0} ready
              </span>
            </div>
            {dep?.image && (
              <div className="mt-2">
                <span className="text-[var(--o-text-secondary)]">Image</span>
                <p className="mt-0.5 break-all font-mono text-[10px] text-[var(--o-text-secondary)]">
                  {dep.image}
                </p>
              </div>
            )}
          </div>
        </section>

        {/* Pods */}
        {detail && detail.pods.length > 0 && (
          <section>
            <SectionHead icon={Box} title={`Pods (${detail.pods.length})`} />
            <div className="space-y-1.5">
              {detail.pods.map((pod) => (
                <div
                  key={pod.name}
                  className="flex items-center justify-between rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] px-3 py-2 text-xs"
                >
                  <span className="truncate font-mono" title={pod.name}>
                    {pod.name.length > 36 ? `...${pod.name.slice(-33)}` : pod.name}
                  </span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span
                      className={clsx(
                        "rounded px-1.5 py-0.5 font-mono",
                        pod.phase === "Running"
                          ? "bg-green-500/10 text-green-400"
                          : "bg-yellow-500/10 text-yellow-400",
                      )}
                    >
                      {pod.ready}/{pod.total}
                    </span>
                    {pod.restarts > 0 && (
                      <span className="text-orange-400" title="Restarts">
                        {pod.restarts}x
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Events */}
        {detail && detail.events.length > 0 && (
          <section>
            <SectionHead icon={AlertTriangle} title={`Events (${detail.events.length})`} />
            <div className="max-h-[200px] space-y-1 overflow-y-auto">
              {detail.events.map((ev, i) => (
                <div
                  key={i}
                  className={clsx(
                    "rounded-lg border px-3 py-2 text-[11px]",
                    ev.type === "Warning"
                      ? "border-orange-500/20 bg-orange-500/5"
                      : "border-[var(--o-border)] bg-[var(--o-bg-raised)]",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{ev.reason}</span>
                    <span className="text-[var(--o-text-secondary)]">
                      {ev.count && ev.count > 1 ? `${ev.count}x` : ""}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[var(--o-text-secondary)] line-clamp-2">{ev.message}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Logs preview */}
        {detail && detail.logs && detail.logs !== "(unable to fetch logs)" && (
          <section>
            <SectionHead icon={Terminal} title="Recent Logs" />
            <pre className="max-h-[200px] overflow-auto rounded-lg border border-[var(--o-border)] bg-[#0d1117] p-3 font-mono text-[10px] leading-relaxed text-green-300">
              {detail.logs.split("\n").slice(-30).join("\n")}
            </pre>
          </section>
        )}

        {/* Version Gap */}
        {!mapping.is_infrastructure && (
          <section>
            <SectionHead icon={GitBranch} title="Version Gap" />
            <div className="rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-3 text-sm">
              {gap?.status === "unknown" ? (
                <p className="text-xs text-[var(--o-text-secondary)]">
                  Unable to determine. Image tag may not contain a git ref.
                </p>
              ) : gap?.status === "current" ? (
                <p className="text-xs text-green-400">Up to date with HEAD</p>
              ) : (
                <div>
                  <div className="flex items-center justify-between">
                    <span>Commits behind</span>
                    <span className="font-mono text-orange-400">{gap?.gap_count ?? "?"}</span>
                  </div>
                  {gap?.deployed_ref && (
                    <p className="mt-1 font-mono text-[10px] text-[var(--o-text-secondary)]">
                      ref: {gap.deployed_ref}
                    </p>
                  )}
                </div>
              )}
            </div>
          </section>
        )}

        {/* Repository */}
        {mapping.context_source_name && (
          <section>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--o-text-secondary)]">
              Repository
            </h4>
            <div className="rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{mapping.context_source_name}</span>
                {mapping.context_source_url && (
                  <a
                    href={mapping.context_source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="o-btn-ghost p-1 text-[var(--o-accent)]"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
              </div>
            </div>
          </section>
        )}

        {detailQuery.isLoading && (
          <div className="flex items-center justify-center py-6 text-[var(--o-text-secondary)]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            <span className="text-xs">Loading live data...</span>
          </div>
        )}
      </div>

      {/* Footer: Ask Orbi */}
      {!mapping.is_infrastructure && (
        <div className="border-t border-[var(--o-border)] p-4">
          <button
            type="button"
            className="o-btn-primary flex w-full items-center justify-center gap-1.5 text-sm"
            onClick={() => debugMut.mutate(
              `Help me debug the ${mapping.deployment_name} service in namespace ${mapping.deployment_namespace}. Check its pod status, recent logs, and events.`,
            )}
            disabled={debugMut.isPending}
          >
            {debugMut.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <MessageCircle className="h-3.5 w-3.5" />
            )}
            Ask Orbi about this service
          </button>
        </div>
      )}
    </div>
  );
}

function SectionHead({ icon: Icon, title }: { icon: React.ElementType; title: string }) {
  return (
    <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--o-text-secondary)]">
      <Icon className="h-3 w-3" />
      {title}
    </h4>
  );
}
