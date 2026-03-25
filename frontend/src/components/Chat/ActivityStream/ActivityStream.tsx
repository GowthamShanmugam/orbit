import clsx from "clsx";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Loader2,
  Search,
  Terminal,
} from "lucide-react";
import { useEffect, useState } from "react";

type ActionStatus = "done" | "running" | "pending";

interface StreamAction {
  id: string;
  icon: "search" | "terminal" | "dot";
  label: string;
  status: ActionStatus;
  durationMs?: number;
}

const SAMPLE_ACTIONS: StreamAction[] = [
  {
    id: "1",
    icon: "search",
    label: "Scan repository structure",
    status: "done",
    durationMs: 420,
  },
  {
    id: "2",
    icon: "terminal",
    label: "Run static analysis on /src",
    status: "running",
  },
  {
    id: "3",
    icon: "dot",
    label: "Prepare context bundle for model",
    status: "pending",
  },
];

function ActionIcon({ kind }: { kind: StreamAction["icon"] }) {
  const cls = "h-3.5 w-3.5 shrink-0";
  if (kind === "search") return <Search className={cls} />;
  if (kind === "terminal") return <Terminal className={cls} />;
  return <CircleDot className={cls} />;
}

function StatusIcon({ status }: { status: ActionStatus }) {
  if (status === "done") {
    return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-[#3fb950]" />;
  }
  if (status === "running") {
    return (
      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[#58a6ff]" />
    );
  }
  return (
    <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-[#484f58]" />
  );
}

export default function ActivityStream() {
  const [open, setOpen] = useState(true);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const t = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="border-b border-[#30363d] bg-[#161b22]/80">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-[#21262d]/80"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-[#8b949e]" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-[#8b949e]" />
        )}
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[#58a6ff]" />
        <span className="flex-1 text-xs font-medium text-[#e6edf3]">
          Analyzing…
        </span>
        <span className="font-mono text-[10px] tabular-nums text-[#8b949e]">
          {elapsed}s
        </span>
      </button>
      {open && (
        <ul className="space-y-0 border-t border-[#30363d]/80 px-2 py-2">
          {SAMPLE_ACTIONS.map((a) => (
            <li
              key={a.id}
              className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs text-[#8b949e] transition-colors hover:bg-[#21262d]/60"
            >
              <span className="mt-0.5 text-[#58a6ff]">
                <ActionIcon kind={a.icon} />
              </span>
              <span
                className={clsx(
                  "flex-1",
                  a.status === "pending" && "opacity-60"
                )}
              >
                {a.label}
              </span>
              <span className="flex shrink-0 items-center gap-2">
                {a.durationMs != null && (
                  <span className="font-mono text-[10px] text-[#6e7681]">
                    {a.durationMs}ms
                  </span>
                )}
                <StatusIcon status={a.status} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
