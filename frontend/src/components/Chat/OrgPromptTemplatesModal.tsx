import {
  createOrgPromptTemplate,
  deleteOrgPromptTemplate,
  listOrgPromptTemplates,
  updateOrgPromptTemplate,
} from "@/api/orgPromptTemplates";
import type { OrgPromptTemplate } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Loader2, Pencil, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

type Props = {
  orgId: string;
  open: boolean;
  onClose: () => void;
};

export default function OrgPromptTemplatesModal({
  orgId,
  open,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [sortOrder, setSortOrder] = useState(0);
  const [editing, setEditing] = useState<OrgPromptTemplate | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["org-prompt-templates", orgId],
    queryFn: () => listOrgPromptTemplates(orgId),
    enabled: open && Boolean(orgId),
  });

  useEffect(() => {
    if (!open) {
      setTitle("");
      setBody("");
      setSortOrder(0);
      setEditing(null);
      setFormError(null);
    }
  }, [open]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["org-prompt-templates", orgId] });
  };

  const saveMut = useMutation({
    mutationFn: async () => {
      const t = title.trim();
      const b = body.trim();
      if (!t || !b) throw new Error("Title and prompt text are required.");
      if (editing) {
        return updateOrgPromptTemplate(orgId, editing.id, {
          title: t,
          body: b,
          sort_order: sortOrder,
        });
      }
      return createOrgPromptTemplate(orgId, {
        title: t,
        body: b,
        sort_order: sortOrder,
      });
    },
    onSuccess: () => {
      invalidate();
      setTitle("");
      setBody("");
      setSortOrder(0);
      setEditing(null);
      setFormError(null);
    },
    onError: (e: unknown) => {
      setFormError(e instanceof Error ? e.message : "Save failed");
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteOrgPromptTemplate(orgId, id),
    onSuccess: () => {
      invalidate();
      if (editing?.id) setEditing(null);
    },
  });

  const startEdit = (row: OrgPromptTemplate) => {
    setEditing(row);
    setTitle(row.title);
    setBody(row.body);
    setSortOrder(row.sort_order);
    setFormError(null);
  };

  const cancelEdit = () => {
    setEditing(null);
    setTitle("");
    setBody("");
    setSortOrder(0);
    setFormError(null);
  };

  if (!open) return null;

  const templates = data?.templates ?? [];
  const canManage = data?.can_manage ?? false;

  return (
    <div
      className="o-modal-backdrop fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="presentation"
      onClick={() => !saveMut.isPending && !deleteMut.isPending && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="org-prompts-title"
        className="o-modal flex max-h-[90vh] w-full max-w-lg flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between border-b border-[var(--o-border)] px-6 py-4">
          <div>
            <h2
              id="org-prompts-title"
              className="text-lg font-semibold text-[var(--o-text)]"
            >
              Team prompts
            </h2>
            <p className="mt-1 text-sm text-[var(--o-text-secondary)]">
              Same text for everyone — use in chat instead of retyping. Only
              organization admins can edit.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="o-btn-icon h-8 w-8 text-[var(--o-text-tertiary)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {isLoading ? (
            <div className="flex justify-center py-8 text-[var(--o-text-secondary)]">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : templates.length === 0 && !canManage ? (
            <p className="text-sm text-[var(--o-text-secondary)]">
              No team prompts yet. Ask an org admin to add some.
            </p>
          ) : (
            <ul className="space-y-2">
              {templates.map((row) => (
                <li
                  key={row.id}
                  className="flex items-start justify-between gap-2 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-[var(--o-text)]">
                      {row.title}
                    </p>
                    <p className="mt-1 line-clamp-2 whitespace-pre-wrap text-xs text-[var(--o-text-secondary)]">
                      {row.body}
                    </p>
                  </div>
                  {canManage && (
                    <div className="flex shrink-0 gap-1">
                      <button
                        type="button"
                        title="Edit"
                        onClick={() => startEdit(row)}
                        className="rounded p-1 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-raised)] hover:text-[var(--o-accent)]"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Delete"
                        disabled={deleteMut.isPending}
                        onClick={() => {
                          if (
                            confirm(`Delete prompt "${row.title}"?`)
                          ) {
                            deleteMut.mutate(row.id);
                          }
                        }}
                        className="rounded p-1 text-[var(--o-text-tertiary)] hover:bg-[var(--o-danger)]/10 hover:text-[var(--o-danger)]"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {canManage && (
            <form
              className="mt-6 space-y-3 border-t border-[var(--o-border)] pt-4"
              onSubmit={(e) => {
                e.preventDefault();
                setFormError(null);
                saveMut.mutate();
              }}
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
                {editing ? "Edit prompt" : "Add prompt"}
              </p>
              {editing && (
                <button
                  type="button"
                  onClick={cancelEdit}
                  className="text-xs text-[var(--o-accent)] hover:underline"
                >
                  Cancel edit
                </button>
              )}
              <div>
                <label className="mb-1 block text-xs text-[var(--o-text-secondary)]">
                  Short label
                </label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="o-input w-full px-3 py-2 text-sm"
                  placeholder="e.g. Weekly status report"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--o-text-secondary)]">
                  Prompt text
                </label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={6}
                  className="o-input w-full resize-y px-3 py-2 text-sm"
                  placeholder="Exact instructions sent to the model…"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--o-text-secondary)]">
                  Sort order (optional)
                </label>
                <input
                  type="number"
                  value={sortOrder}
                  onChange={(e) => setSortOrder(Number(e.target.value) || 0)}
                  className="o-input w-24 px-3 py-2 text-sm"
                />
              </div>
              {formError && (
                <p className="text-sm text-[var(--o-danger)]">{formError}</p>
              )}
              <button
                type="submit"
                disabled={saveMut.isPending}
                className={clsx(
                  "o-btn-primary px-4 py-2 text-sm",
                  saveMut.isPending && "opacity-60",
                )}
              >
                {saveMut.isPending && (
                  <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
                )}
                {editing ? "Save changes" : "Add prompt"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
