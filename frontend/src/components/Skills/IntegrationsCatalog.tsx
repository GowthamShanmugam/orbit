import { listIntegrations, testIntegration } from "@/api/skills";
import type { Integration, SkillTestResult } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronRight,
  Circle,
  ExternalLink,
  FileText,
  Github,
  Loader2,
  PlugZap,
  XCircle,
  Zap,
} from "lucide-react";
import { useState } from "react";
import SkillConfigModal from "./SkillConfigModal";

const INTEGRATION_ICONS: Record<string, React.ReactNode> = {
  jira: (
    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
      <Zap className="h-5 w-5 text-[var(--o-accent)]" />
    </div>
  ),
  github: (
    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
      <Github className="h-5 w-5 text-[var(--o-accent)]" />
    </div>
  ),
  "google-drive": (
    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[color-mix(in_srgb,#4285F4_14%,transparent)]">
      <FileText className="h-5 w-5 text-[#4285F4]" />
    </div>
  ),
};

function StatusBadge({ integration }: { integration: Integration }) {
  if (integration.status === "connected") {
    return (
      <div
        className="flex items-center gap-1.5 rounded-full px-2.5 py-1"
        style={{
          backgroundColor: "color-mix(in srgb, var(--o-green) 14%, transparent)",
        }}
      >
        <span className="relative flex h-2 w-2">
          <span
            className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-75"
            style={{ backgroundColor: "var(--o-green)" }}
          />
          <span
            className="relative inline-flex h-2 w-2 rounded-full"
            style={{ backgroundColor: "var(--o-green)" }}
          />
        </span>
        <span className="text-[11px] font-semibold text-[var(--o-green)]">Ready</span>
      </div>
    );
  }
  if (integration.status === "error") {
    return (
      <div
        className="flex items-center gap-1.5 rounded-full px-2.5 py-1"
        style={{
          backgroundColor: "color-mix(in srgb, var(--o-danger) 14%, transparent)",
        }}
      >
        <XCircle className="h-3 w-3 text-[var(--o-danger)]" />
        <span className="text-[11px] font-semibold text-[var(--o-danger)]">Error</span>
      </div>
    );
  }
  if (integration.configured) {
    return (
      <div className="flex items-center gap-1.5 rounded-full bg-[var(--o-bg-subtle)] px-2.5 py-1">
        <CheckCircle2 className="h-3 w-3 text-[var(--o-text-tertiary)]" />
        <span className="text-[11px] font-semibold text-[var(--o-text-tertiary)]">Configured</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 rounded-full bg-[var(--o-bg-subtle)] px-2.5 py-1">
      <Circle className="h-3 w-3 text-[var(--o-text-tertiary)]" />
      <span className="text-[11px] font-semibold text-[var(--o-text-tertiary)]">
        Not configured
      </span>
    </div>
  );
}

export default function IntegrationsCatalog() {
  const qc = useQueryClient();
  const [configIntegration, setConfigIntegration] = useState<Integration | null>(null);
  const [testResult, setTestResult] = useState<SkillTestResult | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["integrations"],
    queryFn: listIntegrations,
  });

  const integrations = query.data?.integrations ?? [];

  const testMut = useMutation({
    mutationFn: (id: string) => testIntegration(id),
    onSuccess: (data) => {
      setTestResult(data);
      qc.invalidateQueries({ queryKey: ["integrations"] });
    },
  });

  return (
    <div className="mx-auto max-w-4xl overflow-hidden p-6">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <PlugZap className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-[var(--o-text)]">Integrations</h1>
            <p className="text-sm text-[var(--o-text-secondary)]">
              Configure your credentials here. All configured integrations are automatically
              available in chat.
            </p>
          </div>
        </div>
      </div>

      {/* Loading */}
      {query.isLoading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--o-text-tertiary)]" />
        </div>
      )}

      {/* Integration cards */}
      <div className="grid gap-4">
        {integrations.map((itg) => {
          const icon = INTEGRATION_ICONS[itg.icon ?? ""] ?? (
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
              <PlugZap className="h-5 w-5 text-[var(--o-accent)]" />
            </div>
          );
          const isReady = itg.status === "connected";

          return (
            <div
              key={itg.id}
              className={`group rounded-xl border bg-[var(--o-bg-raised)] p-5 transition-all hover:shadow-sm ${
                isReady
                  ? "border-[color-mix(in_srgb,var(--o-green)_32%,transparent)]"
                  : itg.status === "error"
                    ? "border-[color-mix(in_srgb,var(--o-danger)_32%,transparent)]"
                    : "border-[var(--o-border)] hover:border-[var(--o-border-hover)]"
              }`}
            >
              <div className="flex items-start gap-4">
                {icon}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <h3 className="text-sm font-semibold text-[var(--o-text)]">{itg.name}</h3>
                    <StatusBadge integration={itg} />
                  </div>

                  <p className="mt-1 text-xs text-[var(--o-text-secondary)] line-clamp-2">
                    {itg.description}
                  </p>

                  {itg.tool_count > 0 && (
                    <p className="mt-2 text-[11px] text-[var(--o-text-tertiary)]">
                      {itg.tool_count} tools available
                    </p>
                  )}

                  {itg.status === "error" && itg.status_message && (
                    <p
                      className="mt-2 break-words rounded px-2 py-1 text-[11px] text-[var(--o-danger)]"
                      style={{
                        backgroundColor: "color-mix(in srgb, var(--o-danger) 6%, transparent)",
                        overflowWrap: "anywhere",
                      }}
                    >
                      {itg.status_message}
                    </p>
                  )}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setConfigIntegration(itg)}
                    className="flex items-center gap-1.5 rounded-lg border border-[var(--o-border)] px-3 py-1.5 text-xs font-medium text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-accent)]/40 hover:text-[var(--o-text)]"
                  >
                    {itg.configured ? "Reconfigure" : "Configure"}
                    <ChevronRight className="h-3 w-3" />
                  </button>

                  {itg.configured && (
                    <button
                      type="button"
                      onClick={() => {
                        setTestingId(itg.id);
                        setTestResult(null);
                        testMut.mutate(itg.id);
                      }}
                      disabled={testMut.isPending && testingId === itg.id}
                      className="o-btn-icon rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                      title="Test connection"
                    >
                      {testMut.isPending && testingId === itg.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <ExternalLink className="h-3.5 w-3.5" />
                      )}
                    </button>
                  )}
                </div>
              </div>

              {/* Test result */}
              {testResult && testingId === itg.id && (
                <div
                  className={`mt-4 rounded-lg border px-4 py-3 text-xs ${
                    testResult.success
                      ? "border-[color-mix(in_srgb,var(--o-green)_22%,transparent)] bg-[color-mix(in_srgb,var(--o-green)_6%,transparent)] text-[var(--o-green)]"
                      : "border-[color-mix(in_srgb,var(--o-danger)_22%,transparent)] bg-[color-mix(in_srgb,var(--o-danger)_6%,transparent)] text-[var(--o-danger)]"
                  }`}
                >
                  {testResult.success ? (
                    <p className="font-medium">
                      Connection successful -- {testResult.tool_count} tools discovered
                    </p>
                  ) : (
                    <p>Connection failed: {testResult.error}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Empty state */}
      {integrations.length === 0 && !query.isLoading && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <PlugZap className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <p className="text-sm text-[var(--o-text-secondary)]">No integrations available</p>
        </div>
      )}

      {/* Config modal */}
      {configIntegration && (
        <SkillConfigModal
          skill={configIntegration}
          onClose={() => setConfigIntegration(null)}
          onSaved={() => {
            setConfigIntegration(null);
            qc.invalidateQueries({ queryKey: ["integrations"] });
          }}
        />
      )}
    </div>
  );
}
