import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { Server } from "lucide-react";
import clsx from "clsx";

interface ServiceNodeData {
  label: string;
  namespace: string;
  repoName: string | null;
  isInfrastructure: boolean;
  [key: string]: unknown;
}

function ServiceNode({ data }: { data: ServiceNodeData }) {
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
          <span className="truncate text-sm font-semibold">{data.label}</span>
          <p className="mt-0.5 text-[10px] text-[var(--o-text-secondary)]">{data.namespace}</p>
        </div>
      </div>

      {data.repoName && (
        <div className="mt-2 text-[10px] text-[var(--o-text-secondary)] truncate" title={data.repoName}>
          {data.repoName}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-[var(--o-accent)]" />
    </div>
  );
}

export default memo(ServiceNode);
