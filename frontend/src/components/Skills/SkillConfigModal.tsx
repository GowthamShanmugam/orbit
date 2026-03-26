import { configureSkill } from "@/api/skills";
import type { McpSkill } from "@/types";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Eye, EyeOff, Loader2, X, XCircle } from "lucide-react";
import { useState } from "react";

interface Props {
  skill: McpSkill;
  onClose: () => void;
  onSaved: () => void;
}

export default function SkillConfigModal({ skill, onClose, onSaved }: Props) {
  const fields = skill.config_schema?.fields ?? [];
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const f of fields) {
      initial[f.key] = "";
    }
    return initial;
  });
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});

  const saveMut = useMutation({
    mutationFn: () => configureSkill(skill.id, { config_values: values }),
    onSuccess: (updated) => {
      if (updated.status === "connected") {
        setTimeout(() => onSaved(), 1200);
      }
    },
  });

  const allRequiredFilled = fields
    .filter((f) => f.required)
    .every((f) => values[f.key]?.trim());

  const result = saveMut.data;
  const connected = result?.status === "connected";
  const failed = result?.status === "error";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--o-border)] px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--o-text)]">
              Configure {skill.name}
            </h2>
            <p className="mt-0.5 text-xs text-[var(--o-text-secondary)]">
              Provide credentials to connect this MCP skill
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="o-btn-icon rounded-lg p-1.5 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-6 py-5">
          {fields.map((field) => (
            <div key={field.key}>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                {field.label}
                {field.required && <span className="ml-0.5 text-red-400">*</span>}
              </label>
              <div className="relative">
                <input
                  type={
                    field.type === "password" && !showPasswords[field.key]
                      ? "password"
                      : "text"
                  }
                  value={values[field.key] ?? ""}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                  }
                  placeholder={field.placeholder ?? ""}
                  disabled={saveMut.isPending || connected}
                  className="o-input w-full rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--o-accent)] disabled:opacity-50"
                />
                {field.type === "password" && (
                  <button
                    type="button"
                    onClick={() =>
                      setShowPasswords((p) => ({
                        ...p,
                        [field.key]: !p[field.key],
                      }))
                    }
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--o-text-tertiary)] hover:text-[var(--o-text)]"
                  >
                    {showPasswords[field.key] ? (
                      <EyeOff className="h-3.5 w-3.5" />
                    ) : (
                      <Eye className="h-3.5 w-3.5" />
                    )}
                  </button>
                )}
              </div>
              {field.help_url && (
                <a
                  href={field.help_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-[var(--o-accent)] transition-opacity hover:opacity-80"
                >
                  <ExternalLink className="h-3 w-3" />
                  {field.help_text ?? "Learn more"}
                </a>
              )}
            </div>
          ))}

          {fields.length === 0 && (
            <p className="text-sm text-[var(--o-text-secondary)]">
              This skill has no configuration fields.
            </p>
          )}

          {connected && (
            <div className="flex items-center gap-2 rounded-lg border border-green-500/20 bg-green-500/5 px-4 py-3 text-xs text-green-400">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <div>
                <p className="font-semibold">Connected successfully</p>
                {result.tool_count > 0 && (
                  <p className="mt-0.5 opacity-80">{result.tool_count} tools available</p>
                )}
              </div>
            </div>
          )}

          {failed && (
            <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3 text-xs text-red-400">
              <XCircle className="h-4 w-4 shrink-0" />
              <div>
                <p className="font-semibold">Connection failed</p>
                {result.status_message && (
                  <p className="mt-0.5 opacity-80">{result.status_message}</p>
                )}
              </div>
            </div>
          )}

          {saveMut.isError && (
            <p className="rounded bg-red-500/10 px-3 py-2 text-xs text-red-400">
              Failed to save: {(saveMut.error as Error)?.message ?? "Unknown error"}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-[var(--o-border)] px-6 py-4">
          <button
            type="button"
            onClick={connected ? onSaved : onClose}
            className="rounded-lg border border-[var(--o-border)] px-4 py-2 text-xs font-medium text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)]"
          >
            {connected ? "Done" : "Cancel"}
          </button>
          {!connected && (
            <button
              type="button"
              onClick={() => saveMut.mutate()}
              disabled={!allRequiredFilled || saveMut.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-4 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saveMut.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
              {saveMut.isPending ? "Connecting..." : failed ? "Retry" : "Save & Connect"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
