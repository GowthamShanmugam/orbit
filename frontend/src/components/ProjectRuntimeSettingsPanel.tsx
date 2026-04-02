import {
  getProjectRuntimeSettings,
  putProjectRuntimeSettings,
  type ProjectRuntimeSettingsPayload,
} from "@/api/projectRuntimeSettings";
import type { RuntimeSettingsUpdate } from "@/api/runtimeSettings";
import {
  RUNTIME_KEYS,
  RUNTIME_LABELS,
  RUNTIME_PARAM_EXPLANATIONS,
} from "@/lib/runtimeLimitsMeta";
import { HelpCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

function closeEnough(a: number, b: number): boolean {
  return Math.abs(a - b) < 1e-6;
}

/** Clear project override when the value matches server global; otherwise set override. */
function buildProjectPatch(
  form: Record<string, number>,
  globalValues: Record<string, number>,
): RuntimeSettingsUpdate {
  const patch: RuntimeSettingsUpdate = {};
  for (const k of RUNTIME_KEYS) {
    const v = form[k];
    const g = globalValues[k];
    if (g === undefined) continue;
    patch[k] = closeEnough(v, g) ? null : v;
  }
  return patch;
}

type Props = {
  projectId: string;
};

const SAVE_SUCCESS_MS = 4500;

export default function ProjectRuntimeSettingsPanel({ projectId }: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [data, setData] = useState<ProjectRuntimeSettingsPayload | null>(null);
  const [form, setForm] = useState<Record<string, number>>({});
  const [helpOpenKey, setHelpOpenKey] = useState<string | null>(null);
  const helpRootRefs = useRef<Map<string, HTMLElement>>(new Map());
  const saveSuccessTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setHelpRoot = (key: string, el: HTMLElement | null) => {
    const m = helpRootRefs.current;
    if (el) m.set(key, el);
    else m.delete(key);
  };

  useEffect(() => {
    if (helpOpenKey === null) return;
    const onPointerDown = (e: PointerEvent) => {
      const root = helpRootRefs.current.get(helpOpenKey);
      const t = e.target as Node;
      if (root && !root.contains(t)) setHelpOpenKey(null);
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [helpOpenKey]);

  useEffect(() => {
    if (helpOpenKey === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setHelpOpenKey(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [helpOpenKey]);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const d = await getProjectRuntimeSettings(projectId);
      setData(d);
      setForm({ ...d.values });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load project runtime settings");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    return () => {
      if (saveSuccessTimerRef.current) clearTimeout(saveSuccessTimerRef.current);
    };
  }, []);

  function clearSaveSuccessTimer() {
    if (saveSuccessTimerRef.current) {
      clearTimeout(saveSuccessTimerRef.current);
      saveSuccessTimerRef.current = null;
    }
  }

  function showSaveSuccess() {
    clearSaveSuccessTimer();
    setSaveSuccess(true);
    saveSuccessTimerRef.current = setTimeout(() => {
      setSaveSuccess(false);
      saveSuccessTimerRef.current = null;
    }, SAVE_SUCCESS_MS);
  }

  async function onSave() {
    if (!data?.allow_write) return;
    setSaving(true);
    setError(null);
    setSaveSuccess(false);
    clearSaveSuccessTimer();
    try {
      const patch = buildProjectPatch(form, data.global_values);
      const next = await putProjectRuntimeSettings(projectId, patch);
      setData(next);
      setForm({ ...next.values });
      showSaveSuccess();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  const allowWrite = data?.allow_write ?? false;
  const globalValues = data?.global_values ?? {};
  const envDefaults = data?.env_defaults ?? {};
  const overrideKeys = data?.project_override_keys ?? [];

  return (
    <div>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
        Runtime limits (this project)
      </h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[var(--o-text-secondary)]">
        These limits apply to chats in this project. They stack on top of{" "}
        <strong className="font-medium text-[var(--o-text)]">server runtime limits</strong> (Settings →
        Runtime limits). Matching the server value clears this project&apos;s override for that field.
        Environment defaults are shown for reference.
      </p>

      {loading ? (
        <p className="mt-4 text-sm text-[var(--o-text-secondary)]">Loading…</p>
      ) : (
        <>
          {!allowWrite && (
            <p className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200/90">
              You can view effective values. Editing requires project write access and{" "}
              RUNTIME_SETTINGS_ALLOW_WRITE=true on the server.
            </p>
          )}
          {error && (
            <p className="mt-4 text-sm text-red-400" role="alert">
              {error}
            </p>
          )}
          <div className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 md:grid-cols-2 2xl:grid-cols-3">
            {RUNTIME_KEYS.map((key) => (
              <label
                key={key}
                className="flex min-w-0 flex-col rounded-lg border border-[var(--o-border)] bg-[var(--o-surface)]/40 p-3"
              >
                <span className="flex items-start gap-1.5">
                  <span className="min-w-0 flex-1 text-sm font-medium leading-snug text-[var(--o-text)]">
                    {RUNTIME_LABELS[key]}
                  </span>
                  <span ref={(el) => setHelpRoot(key, el)} className="relative mt-0.5 shrink-0">
                    <button
                      type="button"
                      className="inline-flex cursor-pointer rounded text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--o-accent)] data-[open=true]:text-[var(--o-accent)]"
                      aria-label={`Explain ${RUNTIME_LABELS[key]}`}
                      aria-expanded={helpOpenKey === key}
                      aria-controls={`proj-runtime-help-${key}`}
                      data-open={helpOpenKey === key ? "true" : undefined}
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setHelpOpenKey((k) => (k === key ? null : key));
                      }}
                    >
                      <HelpCircle className="h-4 w-4" aria-hidden />
                    </button>
                    {helpOpenKey === key && (
                      <div
                        id={`proj-runtime-help-${key}`}
                        role="region"
                        aria-label={`${RUNTIME_LABELS[key]} explanation`}
                        className="absolute right-0 top-full z-20 mt-1 w-[min(calc(100vw-2rem),18rem)] rounded-md border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-2.5 text-left text-xs leading-relaxed text-[var(--o-text-secondary)] shadow-[var(--o-shadow-md)]"
                      >
                        {RUNTIME_PARAM_EXPLANATIONS[key]}
                      </div>
                    )}
                  </span>
                </span>
                <span
                  className="mt-0.5 truncate font-mono text-[10px] text-[var(--o-text-tertiary)]"
                  title={key}
                >
                  {key}
                </span>
                <input
                  type="number"
                  step={key === "AI_TOOL_SSE_HEARTBEAT_SEC" ? "0.1" : "1"}
                  className="mt-2 w-full min-w-0 rounded-md border border-[var(--o-border)] bg-[var(--o-surface)] px-2.5 py-1.5 text-sm text-[var(--o-text)]"
                  value={form[key] ?? ""}
                  onChange={(e) => {
                    setSaveSuccess(false);
                    clearSaveSuccessTimer();
                    const v = parseFloat(e.target.value);
                    setForm((prev) => ({
                      ...prev,
                      [key]: Number.isFinite(v) ? v : prev[key] ?? 0,
                    }));
                  }}
                  disabled={!allowWrite || saving}
                />
                <span className="mt-1.5 text-[11px] leading-tight text-[var(--o-text-tertiary)]">
                  {overrideKeys.includes(key) ? (
                    <>
                      <span className="text-[var(--o-accent)]">Project override</span>
                      <span aria-hidden> · </span>
                      server {globalValues[key]}
                    </>
                  ) : (
                    <>
                      Server {globalValues[key]}
                      <span aria-hidden> · </span>
                      env {envDefaults[key]}
                    </>
                  )}
                </span>
              </label>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void onSave()}
              disabled={!allowWrite || saving || loading}
              className="o-btn-ghost rounded-lg border border-[var(--o-border)] px-4 py-2 text-sm disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save project runtime limits"}
            </button>
            {saveSuccess && (
              <p
                role="status"
                aria-live="polite"
                className="text-sm font-medium text-emerald-400/95"
              >
                Saved — project runtime limits updated.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
