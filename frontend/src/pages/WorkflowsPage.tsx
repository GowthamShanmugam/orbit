import { listWorkflows, createWorkflow, deleteWorkflow } from "@/api/workflows";
import type { Workflow, CreateWorkflowInput } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bug,
  ClipboardList,
  FileStack,
  FileText,
  LayoutList,
  Loader2,
  MessageSquare,
  Plus,
  ShieldAlert,
  Trash2,
  Workflow as WorkflowIcon,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";

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

export default function WorkflowsPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [prompt, setPrompt] = useState("");

  const workflowsQuery = useQuery({
    queryKey: ["workflows"],
    queryFn: listWorkflows,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteWorkflow(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workflows"] }),
  });

  const createMut = useMutation({
    mutationFn: (input: CreateWorkflowInput) => createWorkflow(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      setShowCreate(false);
      setName("");
      setDesc("");
      setPrompt("");
    },
  });

  const workflows = workflowsQuery.data ?? [];
  const builtIn = workflows.filter((w) => w.is_builtin);
  const custom = workflows.filter((w) => !w.is_builtin);

  return (
    <div className="mx-auto max-w-5xl p-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--o-text)]">Workflows</h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[var(--o-text-secondary)]">
            Workflows guide the AI through structured task patterns. Select a workflow in any session's chat prompt before sending a message.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="o-btn-ghost inline-flex items-center gap-2 border border-[var(--o-border)] px-3 py-2 text-sm hover:border-[var(--o-accent)]/40 hover:shadow-sm"
        >
          <Plus className="h-4 w-4" />
          New Workflow
        </button>
      </div>

      {workflowsQuery.isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-[var(--o-text-secondary)]" />
        </div>
      ) : (
        <div className="space-y-8">
          <div>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
              Built-in
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {builtIn.map((wf: Workflow) => {
                const Icon = getIcon(wf.icon);
                return (
                  <div
                    key={wf.id}
                    className="rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-4 transition-shadow hover:shadow-sm"
                  >
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--o-accent-muted)]">
                        <Icon className="h-4 w-4 text-[var(--o-accent)]" />
                      </div>
                      <p className="text-sm font-medium text-[var(--o-text)]">{wf.name}</p>
                    </div>
                    <p className="mt-2.5 text-xs leading-relaxed text-[var(--o-text-secondary)]">
                      {wf.description}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {custom.length > 0 && (
            <div>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
                Custom
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {custom.map((wf: Workflow) => {
                  const Icon = getIcon(wf.icon);
                  return (
                    <div
                      key={wf.id}
                      className="rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-4 transition-shadow hover:shadow-sm"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--o-accent-muted)]">
                            <Icon className="h-4 w-4 text-[var(--o-accent)]" />
                          </div>
                          <p className="text-sm font-medium text-[var(--o-text)]">{wf.name}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => deleteMut.mutate(wf.id)}
                          disabled={deleteMut.isPending}
                          className="shrink-0 rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-danger)]/10 hover:text-[var(--o-danger)]"
                          title="Delete workflow"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <p className="mt-2.5 text-xs leading-relaxed text-[var(--o-text-secondary)]">
                        {wf.description}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <p className="text-xs text-[var(--o-text-tertiary)]">
            {workflows.length} workflow{workflows.length !== 1 ? "s" : ""} available.
          </p>
        </div>
      )}

      {showCreate && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          onClick={() => !createMut.isPending && setShowCreate(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-[var(--o-border)] px-6 py-5">
              <h2 className="text-lg font-semibold text-[var(--o-text)]">New workflow</h2>
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="rounded p-1 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <form
              className="space-y-4 p-6"
              onSubmit={(e) => {
                e.preventDefault();
                if (!name.trim() || createMut.isPending) return;
                createMut.mutate({
                  name: name.trim(),
                  slug: name.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, ""),
                  description: desc.trim() || name.trim(),
                  system_prompt: prompt.trim(),
                });
              }}
            >
              <div>
                <label htmlFor="wf-name" className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">Name</label>
                <input
                  id="wf-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="o-input w-full px-3 py-2.5 text-sm"
                  placeholder="e.g. Code Review"
                  autoFocus
                />
              </div>
              <div>
                <label htmlFor="wf-desc" className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">Description</label>
                <input
                  id="wf-desc"
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  className="o-input w-full px-3 py-2.5 text-sm"
                  placeholder="Short description shown in the selector"
                />
              </div>
              <div>
                <label htmlFor="wf-prompt" className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">System prompt</label>
                <textarea
                  id="wf-prompt"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={5}
                  className="o-input w-full resize-none px-3 py-2.5 text-sm"
                  placeholder="Instructions for the AI when this workflow is active..."
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" disabled={createMut.isPending} onClick={() => setShowCreate(false)} className="o-btn-ghost rounded-lg px-4 py-2 text-sm">Cancel</button>
                <button type="submit" disabled={!name.trim() || createMut.isPending} className="o-btn-primary inline-flex items-center gap-2 px-5 py-2 text-sm disabled:opacity-50">
                  {createMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Create
                </button>
              </div>
              {createMut.isError && (
                <p className="text-xs text-[var(--o-danger)]">
                  {(createMut.error as Error).message}
                </p>
              )}
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
