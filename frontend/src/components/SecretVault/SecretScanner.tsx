import { useSecretStore } from "@/stores/secretStore";
import type { ScanMatch } from "@/types";
import clsx from "clsx";
import { AlertTriangle, Shield, X } from "lucide-react";

export default function SecretScanner() {
  const warnings = useSecretStore((s) => s.scanWarnings);
  const show = useSecretStore((s) => s.showScanPopup);
  const dismiss = useSecretStore((s) => s.clearScanWarnings);

  if (!show || warnings.length === 0) return null;

  return (
    <div className="animate-in slide-in-from-bottom-2 fixed bottom-4 right-4 z-50 w-96 rounded-xl border border-[var(--o-warning)]/60 bg-[var(--o-bg-raised)]" style={{ boxShadow: "var(--o-shadow-xl)" }}>
      <div className="flex items-center gap-2 border-b border-[var(--o-border)] px-4 py-3">
        <AlertTriangle className="h-4 w-4 text-[var(--o-warning)]" />
        <span className="flex-1 text-xs font-semibold text-[var(--o-warning)]">
          Potential secrets detected
        </span>
        <button
          type="button"
          onClick={dismiss}
          className="text-[var(--o-text-secondary)] hover:text-[var(--o-text)]"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="max-h-48 overflow-y-auto divide-y divide-[var(--o-bg-subtle)]">
        {warnings.map((w, i) => (
          <WarningItem key={i} match={w} />
        ))}
      </div>
      <div className="flex items-center justify-between border-t border-[var(--o-border)] px-4 py-2.5">
        <p className="text-[10px] text-[var(--o-text-secondary)]">
          Store in the Vault to keep secrets safe
        </p>
        <button
          type="button"
          onClick={dismiss}
          className="o-btn-success flex items-center gap-1 px-2.5 py-1 text-[10px]"
        >
          <Shield className="h-3 w-3" /> Got it
        </button>
      </div>
    </div>
  );
}

function WarningItem({ match }: { match: ScanMatch }) {
  const severityColor: Record<string, string> = {
    high: "bg-[var(--o-danger)]/20 text-[var(--o-danger)]",
    medium: "bg-[var(--o-warning)]/20 text-[var(--o-warning)]",
    low: "bg-[var(--o-accent-ring)]/20 text-[var(--o-accent)]",
  };

  return (
    <div className="px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span
          className={clsx(
            "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase",
            severityColor[match.severity] ?? severityColor.low,
          )}
        >
          {match.severity}
        </span>
        <span className="text-xs font-medium text-[var(--o-text)]">
          {match.pattern_name}
        </span>
      </div>
      <p className="mt-1 font-mono text-[10px] text-[var(--o-text-secondary)] break-all">
        {match.matched_text}
      </p>
      <p className="mt-1 text-[10px] text-[var(--o-text-quaternary)]">{match.suggestion}</p>
    </div>
  );
}
