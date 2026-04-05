import { requestProductTourReplay } from "@/lib/productTour";
import {
  getRuntimeSettings,
  putRuntimeSettings,
  type RuntimeSettingsUpdate,
} from "@/api/runtimeSettings";
import {
  RUNTIME_KEYS,
  RUNTIME_LABELS,
  RUNTIME_PARAM_EXPLANATIONS,
} from "@/lib/runtimeLimitsMeta";
import { useOrbiStore } from "@/stores/orbiStore";
import OrbiDog from "@/components/Orbi/OrbiDog";
import { Dog, HelpCircle, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

function closeEnough(a: number, b: number): boolean {
  return Math.abs(a - b) < 1e-6;
}

function buildPatch(
  values: Record<string, number>,
  envDefaults: Record<string, number>,
): RuntimeSettingsUpdate {
  const patch: RuntimeSettingsUpdate = {};
  for (const k of RUNTIME_KEYS) {
    const v = values[k];
    const d = envDefaults[k];
    if (d === undefined) continue;
    patch[k] = closeEnough(v, d) ? null : v;
  }
  return patch;
}

const SAVE_SUCCESS_MS = 4500;

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [overriddenKeys, setOverriddenKeys] = useState<string[]>([]);
  const [allowWrite, setAllowWrite] = useState(true);
  const [envDefaults, setEnvDefaults] = useState<Record<string, number>>({});
  const [form, setForm] = useState<Record<string, number>>({});
  /** Which parameter's help popover is open (one at a time). */
  const [helpOpenKey, setHelpOpenKey] = useState<string | null>(null);
  const helpRootRefs = useRef<Map<string, HTMLElement>>(new Map());
  const saveSuccessTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setHelpRoot = (key: string, el: HTMLElement | null) => {
    const m = helpRootRefs.current;
    if (el) {
      m.set(key, el);
    } else {
      m.delete(key);
    }
  };

  useEffect(() => {
    if (helpOpenKey === null) return;
    const onPointerDown = (e: PointerEvent) => {
      const root = helpRootRefs.current.get(helpOpenKey);
      const t = e.target as Node;
      if (root && !root.contains(t)) {
        setHelpOpenKey(null);
      }
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [helpOpenKey]);

  useEffect(() => {
    if (helpOpenKey === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setHelpOpenKey(null);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [helpOpenKey]);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const data = await getRuntimeSettings();
      setForm({ ...data.values });
      setEnvDefaults({ ...data.env_defaults });
      setOverriddenKeys(data.overridden_keys);
      setAllowWrite(data.allow_write);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, []);

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
    if (!allowWrite) return;
    setSaving(true);
    setError(null);
    setSaveSuccess(false);
    clearSaveSuccessTimer();
    try {
      const patch = buildPatch(form, envDefaults);
      const data = await putRuntimeSettings(patch);
      setForm({ ...data.values });
      setEnvDefaults({ ...data.env_defaults });
      setOverriddenKeys(data.overridden_keys);
      setAllowWrite(data.allow_write);
      showSaveSuccess();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-8 sm:py-8">
      <h1 className="text-xl font-semibold text-[var(--o-text)]">Settings</h1>
      <p className="mt-3 text-sm leading-relaxed text-[var(--o-text-secondary)]">
        Preferences live in the top bar and sidebar. Runtime limits below apply to this server; values
        equal to the environment default clear any database override for that key.
      </p>

      <div className="mt-6 border-t border-[var(--o-border)] pt-5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
          Runtime limits
        </h2>
        {loading ? (
          <p className="mt-3 text-sm text-[var(--o-text-secondary)]">Loading…</p>
        ) : (
          <>
            {!allowWrite && (
              <p className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200/90">
                Writes are disabled (RUNTIME_SETTINGS_ALLOW_WRITE=false). You can still view
                effective values.
              </p>
            )}
            {error && (
              <p className="mt-3 text-sm text-red-400" role="alert">
                {error}
              </p>
            )}
            <div className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 md:grid-cols-2 2xl:grid-cols-3">
              {RUNTIME_KEYS.map((key) => (
                <label
                  key={key}
                  className="flex min-w-0 flex-col rounded-lg border border-[var(--o-border)] bg-[var(--o-surface)]/40 p-3"
                >
                  <span className="flex items-start gap-1.5">
                    <span className="min-w-0 flex-1 text-sm font-medium leading-snug text-[var(--o-text)]">
                      {RUNTIME_LABELS[key]}
                    </span>
                    <span
                      ref={(el) => setHelpRoot(key, el)}
                      className="relative mt-0.5 shrink-0"
                    >
                      <button
                        type="button"
                        className="inline-flex cursor-pointer rounded text-[var(--o-text-tertiary)] transition-colors hover:text-[var(--o-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--o-accent)] data-[open=true]:text-[var(--o-accent)]"
                        aria-label={`Explain ${RUNTIME_LABELS[key]}`}
                        aria-expanded={helpOpenKey === key}
                        aria-controls={`runtime-help-${key}`}
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
                          id={`runtime-help-${key}`}
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
                    {overriddenKeys.includes(key) ? (
                      <>
                        <span className="text-[var(--o-accent)]">Override</span>
                        <span aria-hidden> · </span>
                        env {envDefaults[key]}
                      </>
                    ) : (
                      <>Env default {envDefaults[key]}</>
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
                {saving ? "Saving…" : "Save runtime limits"}
              </button>
              {saveSuccess && (
                <p
                  role="status"
                  aria-live="polite"
                  className="text-sm font-medium text-emerald-400/95"
                >
                  Saved — server runtime limits updated.
                </p>
              )}
            </div>
          </>
        )}
      </div>

      <div className="mt-8 border-t border-[var(--o-border)] pt-5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
          <span className="inline-flex items-center gap-1.5">
            <Dog className="h-3.5 w-3.5" aria-hidden />
            Orbi — AI companion
          </span>
        </h2>
        <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
          A friendly dog that reacts to what you're doing — typing, thinking, errors, and more.
        </p>
        <OrbiSettings />
      </div>

      <div className="mt-8 border-t border-[var(--o-border)] pt-5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
          Welcome tour
        </h2>
        <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
          Replay the short introduction to the workspace layout and context.
        </p>
        <button
          type="button"
          onClick={() => requestProductTourReplay()}
          className="o-btn-primary mt-3 inline-flex items-center gap-2 px-4 py-2 text-sm"
        >
          <Sparkles className="h-4 w-4 shrink-0 opacity-95" aria-hidden />
          Show welcome tour
        </button>
      </div>
    </div>
  );
}

/* ─── Orbi settings sub-component ─────────────────────────────────── */

function OrbiSettings() {
  const visible = useOrbiStore((s) => s.visible);
  const name = useOrbiStore((s) => s.name);
  const setVisible = useOrbiStore((s) => s.setVisible);
  const setName = useOrbiStore((s) => s.setName);
  const currentState = useOrbiStore((s) => s.state);

  return (
    <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-8">
      {/* preview */}
      <div className="flex flex-col items-center gap-1">
        <div className="rounded-xl border border-[var(--o-border)] bg-[var(--o-surface)]/40 p-3">
          <OrbiDog state={currentState} size={64} />
        </div>
        <span className="text-[10px] text-[var(--o-text-tertiary)]">
          {currentState}
        </span>
      </div>

      {/* controls */}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        {/* toggle */}
        <label className="flex items-center gap-2.5 text-sm text-[var(--o-text)]">
          <input
            type="checkbox"
            checked={visible}
            onChange={(e) => setVisible(e.target.checked)}
            className="h-4 w-4 accent-[var(--o-accent)]"
          />
          Show {name || "Orbi"}
        </label>

        {/* name */}
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-medium text-[var(--o-text-secondary)]">Name</span>
          <input
            type="text"
            value={name}
            maxLength={20}
            onChange={(e) => setName(e.target.value)}
            className="w-40 rounded-md border border-[var(--o-border)] bg-[var(--o-surface)] px-2.5 py-1.5 text-sm text-[var(--o-text)]"
          />
        </label>

      </div>
    </div>
  );
}
