import {
  listProjectSkills,
  listAvailableSkills,
  installSkillToProject,
  uninstallSkillFromProject,
  type ProjectSkillPlugin,
} from "@/api/skills";
import type { SkillPlugin } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ChevronRight, Loader2, Plus, Search, Sparkles, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

export default function ProjectSkills({
  projectId,
  readOnly,
}: {
  projectId: string;
  readOnly: boolean;
}) {
  const qc = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [builtInOpen, setBuiltInOpen] = useState(true);
  const [installedOpen, setInstalledOpen] = useState(true);

  const query = useQuery({
    queryKey: ["project-skills", projectId],
    queryFn: () => listProjectSkills(projectId),
    enabled: Boolean(projectId),
  });

  const uninstallMut = useMutation({
    mutationFn: (pluginId: string) => uninstallSkillFromProject(projectId, pluginId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["project-skills", projectId] }),
  });

  const skills = query.data?.skills ?? [];
  const builtIn = skills.filter((s) => s.is_builtin);
  const installed = skills.filter((s) => !s.is_builtin && s.installed);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
          Project Skills
        </h2>
        {!readOnly && (
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Skill Pack
          </button>
        )}
      </div>

      {query.isLoading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--o-text-secondary)]" />
        </div>
      ) : skills.length === 0 ? (
        <div className="flex flex-col items-center py-12 text-sm text-[var(--o-text-secondary)]">
          <Sparkles className="mb-2 h-6 w-6 text-[var(--o-text-tertiary)]" />
          No skill packs available. Add skill packs to enable AI skills in this project.
        </div>
      ) : (
        <div className="space-y-4">
          {builtIn.length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setBuiltInOpen((o) => !o)}
                className="mb-2 flex items-center gap-1.5 text-xs font-medium text-[var(--o-text-tertiary)] hover:text-[var(--o-text-secondary)]"
              >
                {builtInOpen ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                Built-in ({builtIn.length})
              </button>
              {builtInOpen && (
                <div className="grid gap-2">
                  {builtIn.map((pack) => (
                    <SkillPackRow key={pack.id} pack={pack} />
                  ))}
                </div>
              )}
            </div>
          )}

          {installed.length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setInstalledOpen((o) => !o)}
                className="mb-2 flex items-center gap-1.5 text-xs font-medium text-[var(--o-text-tertiary)] hover:text-[var(--o-text-secondary)]"
              >
                {installedOpen ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                Installed ({installed.length})
              </button>
              {installedOpen && (
                <div className="grid gap-2">
                  {installed.map((pack) => (
                    <SkillPackRow
                      key={pack.id}
                      pack={pack}
                      onUninstall={!readOnly ? () => uninstallMut.mutate(pack.id) : undefined}
                      isUninstalling={
                        uninstallMut.isPending && uninstallMut.variables === pack.id
                      }
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {showAdd && (
        <AddSkillModal
          projectId={projectId}
          onClose={() => setShowAdd(false)}
          onInstalled={() => {
            setShowAdd(false);
            qc.invalidateQueries({ queryKey: ["project-skills", projectId] });
          }}
        />
      )}
    </div>
  );
}

function SkillPackRow({
  pack,
  onUninstall,
  isUninstalling,
}: {
  pack: ProjectSkillPlugin;
  onUninstall?: () => void;
  isUninstalling?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const invocable = pack.skills.filter((s) => s.user_invocable);

  return (
    <div className="rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-5 transition-all hover:border-[var(--o-border-hover)] hover:shadow-sm">
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[color-mix(in_srgb,var(--o-green)_14%,transparent)]">
          <BookOpen className="h-5 w-5 text-[var(--o-green)]" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h3 className="text-sm font-semibold text-[var(--o-text)]">{pack.name}</h3>
            {pack.is_builtin && (
              <span className="rounded bg-[var(--o-accent-muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--o-accent)]">
                Built-in
              </span>
            )}
            {pack.category_name && (
              <span className="text-[10px] text-[var(--o-text-tertiary)]">
                {pack.category_name}
              </span>
            )}
            <span className="text-[11px] text-[var(--o-text-tertiary)]">
              {invocable.length} skill{invocable.length !== 1 ? "s" : ""}
            </span>
          </div>

          {pack.description && (
            <p className="mt-1 text-xs text-[var(--o-text-secondary)] line-clamp-2">
              {pack.description}
            </p>
          )}

          {invocable.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {invocable.slice(0, expanded ? undefined : 5).map((s) => (
                <span
                  key={s.slug}
                  className="inline-flex items-center gap-1 rounded-md bg-[var(--o-bg-subtle)] px-2 py-1 text-[11px] text-[var(--o-text-secondary)]"
                  title={s.description ?? undefined}
                >
                  <Sparkles className="h-3 w-3 text-[var(--o-green)]" />
                  {s.name}
                </span>
              ))}
              {!expanded && invocable.length > 5 && (
                <button
                  type="button"
                  onClick={() => setExpanded(true)}
                  className="rounded-md bg-[var(--o-bg-subtle)] px-2 py-1 text-[11px] text-[var(--o-accent)] hover:underline"
                >
                  +{invocable.length - 5} more
                </button>
              )}
            </div>
          )}

          {expanded && invocable.length > 0 && (
            <div className="mt-3 space-y-2 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] p-3">
              {invocable.map((s) => (
                <div key={s.slug} className="flex items-start gap-2">
                  <span className="mt-0.5 shrink-0 rounded bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--o-green)]">
                    {s.name}
                  </span>
                  <span className="text-xs text-[var(--o-text-secondary)]">
                    {s.description ?? s.name}
                  </span>
                </div>
              ))}
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="text-[11px] text-[var(--o-accent)] hover:underline"
              >
                Show less
              </button>
            </div>
          )}
        </div>

        {onUninstall && (
          <button
            type="button"
            onClick={onUninstall}
            disabled={isUninstalling}
            className="shrink-0 rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[color-mix(in_srgb,var(--o-danger)_10%,transparent)] hover:text-[var(--o-danger)]"
            title="Remove from project"
          >
            {isUninstalling ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
          </button>
        )}
      </div>
    </div>
  );
}

function AddSkillModal({
  projectId,
  onClose,
  onInstalled,
}: {
  projectId: string;
  onClose: () => void;
  onInstalled: () => void;
}) {
  const [search, setSearch] = useState("");

  const query = useQuery({
    queryKey: ["available-skills", projectId],
    queryFn: () => listAvailableSkills(projectId),
  });

  const installMut = useMutation({
    mutationFn: (pluginId: string) => installSkillToProject(projectId, pluginId),
    onSuccess: () => onInstalled(),
  });

  const available = useMemo(() => {
    const all = query.data?.skills ?? [];
    if (!search.trim()) return all;
    const q = search.toLowerCase();
    return all.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.description?.toLowerCase().includes(q) ||
        s.tags?.some((t) => t.toLowerCase().includes(q)),
    );
  }, [query.data, search]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div
        className="flex w-full max-w-lg flex-col rounded-2xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-xl"
        style={{ maxHeight: "70vh" }}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--o-border)] px-5 py-3">
          <h2 className="text-sm font-semibold text-[var(--o-text)]">Add Skill Pack to Project</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="shrink-0 border-b border-[var(--o-border)] px-5 py-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--o-text-tertiary)]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search available skill packs..."
              className="o-input w-full py-2 pl-8 pr-3 text-sm"
              autoFocus
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {query.isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--o-text-tertiary)]" />
            </div>
          ) : available.length === 0 ? (
            <div className="py-8 text-center text-xs text-[var(--o-text-tertiary)]">
              {search
                ? "No skill packs match your search"
                : "All available skill packs are already installed"}
            </div>
          ) : (
            <div className="space-y-2">
              {available.map((pack) => (
                <AvailablePackRow
                  key={pack.id}
                  pack={pack}
                  onInstall={() => installMut.mutate(pack.id)}
                  isInstalling={installMut.isPending && installMut.variables === pack.id}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AvailablePackRow({
  pack,
  onInstall,
  isInstalling,
}: {
  pack: SkillPlugin;
  onInstall: () => void;
  isInstalling: boolean;
}) {
  const invocable = pack.skills.filter((s) => s.user_invocable);

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-4 py-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[color-mix(in_srgb,var(--o-green)_14%,transparent)]">
          <BookOpen className="h-4 w-4 text-[var(--o-green)]" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[var(--o-text)]">{pack.name}</p>
          <p className="text-xs text-[var(--o-text-tertiary)]">
            {invocable.length} skill{invocable.length !== 1 ? "s" : ""}
            {pack.description && <> &middot; {pack.description}</>}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={onInstall}
        disabled={isInstalling}
        className="flex shrink-0 items-center gap-1 rounded-lg bg-[var(--o-accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {isInstalling ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
        Install
      </button>
    </div>
  );
}
