import { useActivityStore } from "@/stores/activityStore";
import type { ActivityAction } from "@/types";
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
import { useEffect, useRef, useState } from "react";

function ActionIcon({ kind }: { kind: ActivityAction["icon"] }) {
  const cls = "h-3.5 w-3.5 shrink-0";
  if (kind === "search") return <Search className={cls} />;
  if (kind === "terminal") return <Terminal className={cls} />;
  return <CircleDot className={cls} />;
}

function StatusIcon({ status }: { status: ActivityAction["status"] }) {
  if (status === "done") {
    return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-[var(--o-green)]" />;
  }
  if (status === "running") {
    return (
      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[var(--o-accent)]" />
    );
  }
  return (
    <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-[var(--o-border-subtle)]" />
  );
}

export default function ActivityStream() {
  const actions = useActivityStore((s) => s.actions);
  const isStreaming = useActivityStore((s) => s.isStreaming);
  const [open, setOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevStreamingRef = useRef(false);

  useEffect(() => {
    if (isStreaming) {
      setElapsed(0);
      setOpen(false);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
      if (prevStreamingRef.current) {
        setOpen(false);
      }
    }
    prevStreamingRef.current = isStreaming;
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isStreaming]);

  if (!isStreaming && actions.length === 0) return null;

  const running = actions.find((a) => a.status === "running");
  const doneCount = actions.filter((a) => a.status === "done").length;
  const statusLabel = running
    ? running.label
    : isStreaming
      ? "Processing…"
      : `Completed (${doneCount} steps)`;

  return (
    <div className="relative shrink-0 border-b border-[var(--o-border)] bg-[var(--o-bg-raised)]/80" style={{ boxShadow: open ? "var(--o-shadow-sm)" : undefined }}>
      {isStreaming && (
        <div className="absolute inset-x-0 top-0 h-[2px] overflow-hidden">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-[var(--o-accent)]" style={{ animation: "slideRight 1.5s ease-in-out infinite" }} />
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-[var(--o-bg-subtle)]/80"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-[var(--o-text-secondary)]" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-[var(--o-text-secondary)]" />
        )}
        {isStreaming ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[var(--o-accent)]" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-[var(--o-green)]" />
        )}
        <span className="flex-1 truncate text-xs font-medium text-[var(--o-text)]">
          {statusLabel}
        </span>
        {isStreaming && (
          <span className="font-mono text-[10px] tabular-nums text-[var(--o-text-secondary)]">
            {elapsed}s
          </span>
        )}
      </button>
      {open && actions.length > 0 && (
        <ul className="max-h-48 overflow-y-auto border-t border-[var(--o-border)]/80 px-2 py-1.5">
          {actions.map((a) => (
            <li
              key={a.id}
              className="flex items-start gap-2 rounded-md px-2 py-1 text-xs text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)]/60 animate-[fadeIn_0.2s_ease-out]"
            >
              <span className="mt-0.5 text-[var(--o-accent)]">
                <ActionIcon kind={a.icon} />
              </span>
              <span
                className={clsx(
                  "flex-1 truncate",
                  a.status === "pending" && "opacity-60",
                )}
              >
                {a.label}
              </span>
              <span className="flex shrink-0 items-center gap-2">
                {a.durationMs != null && (
                  <span className="font-mono text-[10px] text-[var(--o-text-quaternary)]">
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
