import {
  type AIRule,
  type CreateRuleInput,
  type UpdateRuleInput,
  createAIRule,
  deleteAIRule,
  listAIRules,
  updateAIRule,
} from "@/api/aiRules";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Globe,
  Pencil,
  Plus,
  ScrollText,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useState } from "react";

const CATEGORY_OPTIONS = [
  { value: "identity", label: "Identity" },
  { value: "style", label: "Style" },
  { value: "security", label: "Security" },
  { value: "workflow", label: "Workflow" },
  { value: "coding", label: "Coding" },
  { value: "other", label: "Other" },
];

const CATEGORY_COLORS: Record<string, string> = {
  identity: "bg-blue-500/15 text-blue-400",
  style: "bg-purple-500/15 text-purple-400",
  security: "bg-red-500/15 text-red-400",
  workflow: "bg-amber-500/15 text-amber-400",
  coding: "bg-green-500/15 text-green-400",
  other: "bg-gray-500/15 text-gray-400",
};

function CategoryBadge({ category }: { category: string }) {
  const colors = CATEGORY_COLORS[category] ?? CATEGORY_COLORS.other;
  return (
    <span className={`inline-flex rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${colors}`}>
      {category}
    </span>
  );
}

interface RuleDialogProps {
  initial?: { title: string; content: string; category: string };
  onSave: (data: { title: string; content: string; category: string }) => void;
  onCancel: () => void;
  saving: boolean;
}

function RuleDialog({ initial, onSave, onCancel, saving }: RuleDialogProps) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [content, setContent] = useState(initial?.content ?? "");
  const [category, setCategory] = useState(initial?.category ?? "other");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-lg rounded-xl border border-[var(--o-border)] bg-[var(--o-surface)] p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[var(--o-text)]">
            {initial ? "Edit Rule" : "Add Rule"}
          </h3>
          <button type="button" onClick={onCancel} className="text-[var(--o-text-tertiary)] hover:text-[var(--o-text)]">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--o-text-secondary)]">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Use UBI base images"
              className="w-full rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--o-text-secondary)]">Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] focus:border-[var(--o-accent)] focus:outline-none"
            >
              {CATEGORY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--o-text-secondary)]">Rule content</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={5}
              placeholder="Describe the rule the AI should follow..."
              className="w-full rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none resize-y"
            />
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-[var(--o-border)] px-3 py-1.5 text-xs text-[var(--o-text-secondary)] hover:bg-[var(--o-bg)]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onSave({ title: title.trim(), content: content.trim(), category })}
            disabled={!title.trim() || !content.trim() || saving}
            className="rounded-lg bg-[var(--o-accent)] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

interface Props {
  projectId: string;
}

export default function ProjectAIRules({ projectId }: Props) {
  const queryClient = useQueryClient();
  const qk = ["ai-rules", projectId];

  const { data: rules = [], isLoading } = useQuery({
    queryKey: qk,
    queryFn: () => listAIRules(projectId),
  });

  const globalRules = rules.filter((r) => r.scope === "global");
  const projectRules = rules.filter((r) => r.scope === "project");

  const [globalExpanded, setGlobalExpanded] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit" | null>(null);
  const [editingRule, setEditingRule] = useState<AIRule | null>(null);

  const invalidate = useCallback(() => queryClient.invalidateQueries({ queryKey: qk }), [queryClient, qk]);

  const createMut = useMutation({
    mutationFn: (input: CreateRuleInput) => createAIRule(projectId, input),
    onSuccess: invalidate,
  });

  const updateMut = useMutation({
    mutationFn: ({ ruleId, input }: { ruleId: string; input: UpdateRuleInput }) =>
      updateAIRule(projectId, ruleId, input),
    onSuccess: invalidate,
  });

  const deleteMut = useMutation({
    mutationFn: (ruleId: string) => deleteAIRule(projectId, ruleId),
    onSuccess: invalidate,
  });

  const toggleEnabled = (rule: AIRule) => {
    updateMut.mutate({ ruleId: rule.id, input: { enabled: !rule.enabled } });
  };

  const handleSave = (data: { title: string; content: string; category: string }) => {
    if (dialogMode === "edit" && editingRule) {
      updateMut.mutate(
        { ruleId: editingRule.id, input: { title: data.title, content: data.content, category: data.category } },
        { onSuccess: () => { setDialogMode(null); setEditingRule(null); } },
      );
    } else {
      createMut.mutate(
        { title: data.title, content: data.content, category: data.category },
        { onSuccess: () => setDialogMode(null) },
      );
    }
  };

  if (isLoading) {
    return <div className="text-xs text-[var(--o-text-tertiary)]">Loading rules...</div>;
  }

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2">
          <ScrollText className="h-4 w-4 text-[var(--o-accent)]" />
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
            AI Rules
          </h3>
        </div>
        <p className="mt-1 text-xs text-[var(--o-text-tertiary)]">
          Rules guide how the AI behaves in this project. Global rules apply everywhere.
          Add project-specific rules to customize AI behavior for this project.
        </p>
      </div>

      {/* Global rules (collapsible) */}
      <div>
        <button
          type="button"
          onClick={() => setGlobalExpanded(!globalExpanded)}
          className="flex items-center gap-1.5 text-xs font-medium text-[var(--o-text-secondary)] hover:text-[var(--o-text)]"
        >
          {globalExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <Globe className="h-3.5 w-3.5" />
          Global Rules ({globalRules.length})
        </button>

        {globalExpanded && (
          <div className="mt-2 space-y-2 pl-5">
            {globalRules.map((rule) => (
              <div
                key={rule.id}
                className="rounded-lg border border-[var(--o-border)] bg-[var(--o-surface)]/30 p-3"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-[var(--o-text)]">{rule.title}</span>
                  <CategoryBadge category={rule.category} />
                  <span className="text-[10px] text-[var(--o-text-tertiary)]">system</span>
                </div>
                <p className="mt-1 text-xs text-[var(--o-text-tertiary)] line-clamp-2">{rule.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Project rules */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-medium text-[var(--o-text-secondary)]">
            Project Rules ({projectRules.length})
          </span>
          <button
            type="button"
            onClick={() => { setDialogMode("create"); setEditingRule(null); }}
            className="flex items-center gap-1 rounded-lg bg-[var(--o-accent)] px-2.5 py-1 text-xs font-medium text-white hover:opacity-90"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Rule
          </button>
        </div>

        {projectRules.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--o-border)] p-6 text-center">
            <p className="text-xs text-[var(--o-text-tertiary)]">
              No project rules yet. Add rules to customize how the AI works in this project.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {projectRules.map((rule) => (
              <div
                key={rule.id}
                className={`rounded-lg border border-[var(--o-border)] bg-[var(--o-surface)]/40 p-3 transition-opacity ${
                  !rule.enabled ? "opacity-50" : ""
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-[var(--o-accent)]"
                    checked={rule.enabled}
                    onChange={() => toggleEnabled(rule)}
                  />
                  <span className="flex-1 text-sm font-medium text-[var(--o-text)]">{rule.title}</span>
                  <CategoryBadge category={rule.category} />
                  <button
                    type="button"
                    onClick={() => { setEditingRule(rule); setDialogMode("edit"); }}
                    className="text-[var(--o-text-tertiary)] hover:text-[var(--o-text)]"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteMut.mutate(rule.id)}
                    className="text-[var(--o-text-tertiary)] hover:text-red-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <p className="mt-1 pl-5.5 text-xs text-[var(--o-text-tertiary)] line-clamp-2">{rule.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {dialogMode && (
        <RuleDialog
          initial={editingRule ? { title: editingRule.title, content: editingRule.content, category: editingRule.category } : undefined}
          onSave={handleSave}
          onCancel={() => { setDialogMode(null); setEditingRule(null); }}
          saving={createMut.isPending || updateMut.isPending}
        />
      )}
    </div>
  );
}
