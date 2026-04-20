import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { GitFork } from "lucide-react";

interface RepoNodeData {
  label: string;
  url: string | null;
  childCount: number;
  [key: string]: unknown;
}

function RepoNode({ data }: { data: RepoNodeData }) {
  return (
    <div className="rounded-xl border-2 border-[var(--o-accent)] bg-[var(--o-accent-muted)] px-5 py-3 shadow-lg min-w-[200px] select-none">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--o-accent)]/20">
          <GitFork className="h-4 w-4 text-[var(--o-accent)]" />
        </div>
        <div>
          <p className="text-sm font-bold text-[var(--o-accent)]">{data.label}</p>
          <p className="text-[10px] text-[var(--o-text-secondary)]">
            {data.childCount} service{data.childCount !== 1 ? "s" : ""}
          </p>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-[var(--o-accent)]" />
    </div>
  );
}

export default memo(RepoNode);
