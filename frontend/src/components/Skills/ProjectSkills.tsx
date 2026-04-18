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
import SkillPackCardBody from "./SkillPackCardBody";
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-skills", projectId] });
      qc.invalidateQueries({ queryKey: ["available-skills", projectId] });
    },
  });

  const skills = query.data?.skills ?? [];
  const builtIn = skills.filter((s) => s.is_builtin);
  const installed = skills.filter((s) => !s.is_builtin && s.installed);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
            Project Skills
          </h2>
          <p className="mt-1 text-xs text-[var(--o-text-tertiary)]">
            Skill packs give the AI specialized abilities like code review, testing, and deployment.
          </p>
        </div>
        {!readOnly && (
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
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
            qc.invalidateQueries({ queryKey: ["available-skills", projectId] });
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
  return (
    <SkillPackCardBody
      pack={pack}
      showCustomBadges
      action={
        onUninstall ? (
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
        ) : undefined
      }
    />
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
    <div className="o-modal-backdrop fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="flex w-full max-w-lg flex-col rounded-2xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-xl"
        style={{ maxHeight: "70vh" }}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--o-border)] px-5 py-3">
          <h2 className="text-sm font-semibold text-[var(--o-text)]">Add Skill Pack</h2>
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
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--o-accent-muted)]">
          <BookOpen className="h-4 w-4 text-[var(--o-accent)]" />
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
