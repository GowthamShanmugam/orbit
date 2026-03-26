import { listSkills, testSkillConnection, toggleSkill, refreshSkillTools } from "@/api/skills";
import type { McpSkill, SkillTestResult } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronRight,
  Circle,
  ExternalLink,
  Github,
  Loader2,
  PlugZap,
  Power,
  RefreshCw,
  XCircle,
  Zap,
} from "lucide-react";
import { useState } from "react";
import SkillConfigModal from "./SkillConfigModal";

const SKILL_ICONS: Record<string, React.ReactNode> = {
  jira: (
    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10 text-blue-500">
      <Zap className="h-5 w-5" />
    </div>
  ),
  github: (
    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-500/10 text-gray-300">
      <Github className="h-5 w-5" />
    </div>
  ),
};

function StatusIndicator({ skill }: { skill: McpSkill }) {
  if (skill.enabled && skill.status === "connected") {
    return (
      <div className="flex items-center gap-1.5 rounded-full bg-green-500/10 px-2.5 py-1">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
        </span>
        <span className="text-[11px] font-semibold text-green-500">Connected</span>
      </div>
    );
  }
  if (skill.status === "error") {
    return (
      <div className="flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1">
        <XCircle className="h-3 w-3 text-red-500" />
        <span className="text-[11px] font-semibold text-red-500">Error</span>
      </div>
    );
  }
  if (skill.enabled && skill.status === "configured") {
    return (
      <div className="flex items-center gap-1.5 rounded-full bg-yellow-500/10 px-2.5 py-1">
        <Circle className="h-3 w-3 fill-yellow-500 text-yellow-500" />
        <span className="text-[11px] font-semibold text-yellow-500">Enabled</span>
      </div>
    );
  }
  if (skill.has_config) {
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
      <span className="text-[11px] font-semibold text-[var(--o-text-tertiary)]">Not connected</span>
    </div>
  );
}

export default function SkillCatalog() {
  const qc = useQueryClient();
  const [configSkill, setConfigSkill] = useState<McpSkill | null>(null);
  const [testResult, setTestResult] = useState<SkillTestResult | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  const skillsQuery = useQuery({
    queryKey: ["skills"],
    queryFn: listSkills,
  });

  const toggleMut = useMutation({
    mutationFn: (id: string) => toggleSkill(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });

  const testMut = useMutation({
    mutationFn: (id: string) => testSkillConnection(id),
    onSuccess: (data) => {
      setTestResult(data);
      qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });

  const refreshMut = useMutation({
    mutationFn: (id: string) => refreshSkillTools(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });

  const skills = skillsQuery.data ?? [];

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <PlugZap className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-[var(--o-text)]">Skills</h1>
            <p className="text-sm text-[var(--o-text-secondary)]">
              Connect MCP servers to extend Orbit's AI capabilities
            </p>
          </div>
        </div>
      </div>

      {skillsQuery.isLoading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--o-text-tertiary)]" />
        </div>
      )}

      <div className="grid gap-4">
        {skills.map((skill) => {
          const icon = SKILL_ICONS[skill.icon ?? ""] ?? (
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-500/10 text-purple-400">
              <PlugZap className="h-5 w-5" />
            </div>
          );
          const isConnected = skill.enabled && skill.status === "connected";

          return (
            <div
              key={skill.id}
              className={`group rounded-xl border bg-[var(--o-bg-raised)] p-5 transition-all hover:shadow-sm ${
                isConnected
                  ? "border-green-500/30 hover:border-green-500/50"
                  : skill.status === "error"
                    ? "border-red-500/30 hover:border-red-500/50"
                    : "border-[var(--o-border)] hover:border-[var(--o-border-hover)]"
              }`}
            >
              <div className="flex items-start gap-4">
                {icon}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2.5">
                    <h3 className="text-sm font-semibold text-[var(--o-text)]">
                      {skill.name}
                    </h3>
                    {skill.is_builtin && (
                      <span className="rounded bg-[var(--o-accent-muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--o-accent)]">
                        Built-in
                      </span>
                    )}
                    <StatusIndicator skill={skill} />
                  </div>
                  <p className="mt-1 text-xs text-[var(--o-text-secondary)] line-clamp-2">
                    {skill.description}
                  </p>

                  {skill.tool_count > 0 && (
                    <p className="mt-2 text-[11px] text-[var(--o-text-tertiary)]">
                      {skill.tool_count} tools available
                    </p>
                  )}

                  {skill.status === "error" && skill.status_message && (
                    <p className="mt-2 rounded bg-red-500/5 px-2 py-1 text-[11px] text-red-400">
                      {skill.status_message}
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setConfigSkill(skill)}
                    className="o-btn-icon rounded-lg px-3 py-1.5 text-xs font-medium text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                  >
                    {skill.has_config ? "Reconfigure" : "Configure"}
                    <ChevronRight className="ml-1 inline h-3 w-3" />
                  </button>

                  {skill.has_config && (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setTestingId(skill.id);
                          setTestResult(null);
                          testMut.mutate(skill.id);
                        }}
                        disabled={testMut.isPending && testingId === skill.id}
                        className="o-btn-icon rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                        title="Test connection"
                      >
                        {testMut.isPending && testingId === skill.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <ExternalLink className="h-3.5 w-3.5" />
                        )}
                      </button>

                      {skill.enabled && (
                        <button
                          type="button"
                          onClick={() => refreshMut.mutate(skill.id)}
                          disabled={refreshMut.isPending}
                          className="o-btn-icon rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                          title="Refresh tools"
                        >
                          <RefreshCw className={`h-3.5 w-3.5 ${refreshMut.isPending ? "animate-spin" : ""}`} />
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => toggleMut.mutate(skill.id)}
                        disabled={toggleMut.isPending}
                        className={`o-btn-icon rounded-lg p-1.5 transition-colors ${
                          skill.enabled
                            ? "text-green-500 hover:bg-green-500/10"
                            : "text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                        }`}
                        title={skill.enabled ? "Disable" : "Enable"}
                      >
                        <Power className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </div>
              </div>

              {testResult && testingId === skill.id && (
                <div className={`mt-4 rounded-lg border px-4 py-3 text-xs ${
                  testResult.success
                    ? "border-green-500/20 bg-green-500/5 text-green-400"
                    : "border-red-500/20 bg-red-500/5 text-red-400"
                }`}>
                  {testResult.success ? (
                    <div>
                      <p className="font-medium">Connection successful -- {testResult.tool_count} tools discovered</p>
                      {testResult.tools && testResult.tools.length > 0 && (
                        <ul className="mt-2 space-y-0.5 text-[11px] opacity-80">
                          {testResult.tools.slice(0, 8).map((t) => (
                            <li key={t.name}>
                              <span className="font-mono">{t.name}</span>
                              {t.description && (
                                <span className="ml-1 text-[var(--o-text-tertiary)]">-- {t.description}</span>
                              )}
                            </li>
                          ))}
                          {(testResult.tools.length ?? 0) > 8 && (
                            <li className="text-[var(--o-text-tertiary)]">
                              ...and {(testResult.tools.length ?? 0) - 8} more
                            </li>
                          )}
                        </ul>
                      )}
                    </div>
                  ) : (
                    <p>Connection failed: {testResult.error}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {skills.length === 0 && !skillsQuery.isLoading && (
        <div className="flex flex-col items-center justify-center py-16">
          <PlugZap className="mb-3 h-10 w-10 text-[var(--o-text-tertiary)]" />
          <p className="text-sm text-[var(--o-text-secondary)]">No skills available</p>
          <p className="mt-1 text-xs text-[var(--o-text-tertiary)]">
            Run database migrations to seed the built-in skill catalog
          </p>
        </div>
      )}

      {configSkill && (
        <SkillConfigModal
          skill={configSkill}
          onClose={() => setConfigSkill(null)}
          onSaved={() => {
            setConfigSkill(null);
            qc.invalidateQueries({ queryKey: ["skills"] });
          }}
        />
      )}
    </div>
  );
}
