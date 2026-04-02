import { listWorkflows, createWorkflow } from "@/api/workflows";
import { updateSession } from "@/api/sessions";
import { useSessionStore } from "@/stores/sessionStore";
import type { Workflow } from "@/types";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Bug,
  ChevronDown,
  ClipboardList,
  FileStack,
  FileText,
  LayoutList,
  MessageSquare,
  Plus,
  ShieldAlert,
  Workflow as WorkflowIcon,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";

const ICON_MAP: Record<string, LucideIcon> = {
  MessageSquare,
  Bug,
  ClipboardList,
  ShieldAlert,
  FileText,
  FileStack,
  LayoutList,
};

function getIcon(name?: string | null): LucideIcon {
  if (name && ICON_MAP[name]) return ICON_MAP[name];
  return WorkflowIcon;
}

interface WorkflowSelectorProps {
  projectId: string;
  sessionId: string;
}

export default function WorkflowSelector({
  projectId,
  sessionId,
}: WorkflowSelectorProps) {
  const currentSession = useSessionStore((s) => s.currentSession);
  const setSession = useSessionStore((s) => s.setSession);
  const queryClient = useQueryClient();

  const [open, setOpen] = useState(false);
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customDesc, setCustomDesc] = useState("");
  const [customPrompt, setCustomPrompt] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);

  const { data: workflows = [] } = useQuery({
    queryKey: ["workflows"],
    queryFn: listWorkflows,
  });

  const currentSlug =
    (currentSession?.ai_config as Record<string, string> | null)?.workflow ??
    "general_chat";

  const currentWorkflow =
    workflows.find((w) => w.slug === currentSlug) ??
    workflows.find((w) => w.slug === "general_chat");

  const selectWorkflow = useCallback(
    async (slug: string) => {
      setOpen(false);
      const newConfig = { ...(currentSession?.ai_config ?? {}), workflow: slug };
      try {
        const updated = await updateSession(projectId, sessionId, {
          ai_config: newConfig,
        });
        setSession(updated);
        queryClient.invalidateQueries({
          queryKey: ["session", projectId, sessionId],
        });
      } catch {
        // Optimistic: update local store even if request fails
      }
    },
    [projectId, sessionId, currentSession, setSession, queryClient],
  );

  const createMut = useMutation({
    mutationFn: () =>
      createWorkflow({
        name: customName.trim(),
        slug: customName.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, ""),
        description: customDesc.trim() || customName.trim(),
        system_prompt: customPrompt.trim(),
      }),
    onSuccess: (wf: Workflow) => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      setShowCustomForm(false);
      setCustomName("");
      setCustomDesc("");
      setCustomPrompt("");
      selectWorkflow(wf.slug);
    },
  });

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setShowCustomForm(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const Icon = getIcon(currentWorkflow?.icon);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-2.5 py-1 text-[11px] font-medium text-[var(--o-text-secondary)] transition-all hover:border-[var(--o-accent)]/40 hover:text-[var(--o-text)]"
      >
        <Icon className="h-3 w-3 shrink-0 text-[var(--o-accent)]" />
        <span className="max-w-[180px] truncate">
          {currentWorkflow?.name ?? "General Chat"}
        </span>
        <ChevronDown className="h-3 w-3 shrink-0 opacity-50" />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-30 mb-1.5 w-80 rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-lg">
          {!showCustomForm ? (
            <>
              <div className="border-b border-[var(--o-border)] px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
                  Workflows
                </p>
              </div>
              <div className="max-h-[320px] overflow-y-auto py-1">
                {workflows.map((wf) => {
                  const WfIcon = getIcon(wf.icon);
                  const isActive = wf.slug === currentSlug;
                  return (
                    <button
                      key={wf.id}
                      type="button"
                      onClick={() => selectWorkflow(wf.slug)}
                      className={clsx(
                        "flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors",
                        isActive
                          ? "bg-[var(--o-accent-muted)]"
                          : "hover:bg-[var(--o-bg-subtle)]",
                      )}
                    >
                      <WfIcon
                        className={clsx(
                          "mt-0.5 h-3.5 w-3.5 shrink-0",
                          isActive
                            ? "text-[var(--o-accent)]"
                            : "text-[var(--o-text-tertiary)]",
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <p
                          className={clsx(
                            "text-[12px] font-medium",
                            isActive
                              ? "text-[var(--o-accent)]"
                              : "text-[var(--o-text)]",
                          )}
                        >
                          {wf.name}
                        </p>
                        <p className="mt-0.5 text-[11px] leading-snug text-[var(--o-text-tertiary)]">
                          {wf.description}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>
              <div className="border-t border-[var(--o-border)] px-1 py-1">
                <button
                  type="button"
                  onClick={() => setShowCustomForm(true)}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[11px] font-medium text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                >
                  <Plus className="h-3 w-3" />
                  Load custom
                </button>
              </div>
              <div className="border-t border-[var(--o-border)] px-3 py-1.5">
                <p className="text-[10px] text-[var(--o-text-tertiary)]">
                  {workflows.length} workflow{workflows.length !== 1 ? "s" : ""}{" "}
                  available
                </p>
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-[var(--o-border)] px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
                  Create custom workflow
                </p>
                <button
                  type="button"
                  onClick={() => setShowCustomForm(false)}
                  className="rounded p-0.5 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <form
                className="space-y-2.5 p-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (customName.trim() && !createMut.isPending) {
                    createMut.mutate();
                  }
                }}
              >
                <input
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  placeholder="Workflow name"
                  className="o-input w-full px-2.5 py-1.5 text-[12px]"
                  autoFocus
                />
                <input
                  value={customDesc}
                  onChange={(e) => setCustomDesc(e.target.value)}
                  placeholder="Short description"
                  className="o-input w-full px-2.5 py-1.5 text-[12px]"
                />
                <textarea
                  value={customPrompt}
                  onChange={(e) => setCustomPrompt(e.target.value)}
                  placeholder="System prompt instructions (what should the AI do?)"
                  rows={4}
                  className="o-input w-full resize-none px-2.5 py-1.5 text-[12px]"
                />
                <div className="flex justify-end gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => setShowCustomForm(false)}
                    className="o-btn-ghost px-3 py-1.5 text-[11px]"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={!customName.trim() || createMut.isPending}
                    className="o-btn-primary px-3 py-1.5 text-[11px] disabled:opacity-50"
                  >
                    {createMut.isPending ? "Creating..." : "Create"}
                  </button>
                </div>
                {createMut.isError && (
                  <p className="text-[11px] text-[var(--o-danger)]">
                    {(createMut.error as Error).message}
                  </p>
                )}
              </form>
            </>
          )}
        </div>
      )}
    </div>
  );
}
