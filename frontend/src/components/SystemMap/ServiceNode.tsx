import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { Server, GitBranch } from "lucide-react";
import clsx from "clsx";

interface ServiceNodeData {
  label: string;
  namespace: string;
  status: "healthy" | "degraded" | "failing" | string;
  replicas: number;
  readyReplicas: number;
  gapCount: number | null;
  gapStatus: "current" | "behind" | "unknown";
  repoName: string | null;
  isInfrastructure: boolean;
  [key: string]: unknown;
}

const STATUS_COLORS: Record<string, string> = {
  healthy: "bg-green-400",
  degraded: "bg-yellow-400",
  failing: "bg-red-400",
};

function ServiceNode({ data }: { data: ServiceNodeData }) {
  const statusDot = STATUS_COLORS[data.status] ?? "bg-gray-400";

  return (
    <div
      className={clsx(
        "rounded-xl border px-4 py-3 shadow-md transition-shadow hover:shadow-lg",
        "bg-[var(--o-bg-raised)] border-[var(--o-border)]",
        "min-w-[180px] cursor-pointer select-none",
        data.isInfrastructure && "opacity-60",
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-[var(--o-accent)]" />

      <div className="flex items-start gap-2.5">
        <div
          className={clsx(
            "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
            data.isInfrastructure
              ? "bg-[var(--o-text-secondary)]/10"
              : "bg-[var(--o-accent-muted)]",
          )}
        >
          <Server
            className={clsx(
              "h-3.5 w-3.5",
              data.isInfrastructure ? "text-[var(--o-text-secondary)]" : "text-[var(--o-accent)]",
            )}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className={clsx("h-2 w-2 shrink-0 rounded-full", statusDot)} />
            <span className="truncate text-sm font-semibold">{data.label}</span>
          </div>
          <p className="mt-0.5 text-[10px] text-[var(--o-text-secondary)]">{data.namespace}</p>
        </div>
      </div>

      <div className="mt-2.5 flex items-center gap-2 text-[10px]">
        <span
          className={clsx(
            "rounded-md px-1.5 py-0.5 font-mono",
            data.readyReplicas >= data.replicas
              ? "bg-green-500/10 text-green-400"
              : "bg-yellow-500/10 text-yellow-400",
          )}
        >
          {data.readyReplicas}/{data.replicas} pods
        </span>

        {!data.isInfrastructure && data.gapStatus !== "unknown" && data.gapCount !== null && (
          <span
            className={clsx(
              "flex items-center gap-0.5 rounded-md px-1.5 py-0.5",
              data.gapCount === 0
                ? "bg-green-500/10 text-green-400"
                : "bg-orange-500/10 text-orange-400",
            )}
          >
            <GitBranch className="h-2.5 w-2.5" />
            {data.gapCount === 0 ? "current" : `${data.gapCount} behind`}
          </span>
        )}

        {data.repoName && (
          <span className="truncate text-[var(--o-text-secondary)]" title={data.repoName}>
            {data.repoName}
          </span>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-[var(--o-accent)]" />
    </div>
  );
}

export default memo(ServiceNode);
