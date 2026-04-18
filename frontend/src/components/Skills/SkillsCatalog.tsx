import {
  listSkills,
  importSkillFromGitHub,
  deleteSkillPack,
  type ImportResult,
} from "@/api/skills";
import type { SkillPlugin } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Github,
  Loader2,
  Plus,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import SkillPackCardBody from "./SkillPackCardBody";
import { useMemo, useState } from "react";

const PAGE_SIZE = 6;

export default function SkillsCatalog() {
  const qc = useQueryClient();
  const [filterCategory, _setFilterCategory] = useState<string | null>(null);
  const [search, _setSearch] = useState("");
  const [page, _setPage] = useState(1);

  const setFilterCategory = (v: string | null) => {
    _setFilterCategory(v);
    _setPage(1);
  };
  const setSearch = (v: string) => {
    _setSearch(v);
    _setPage(1);
  };
  const [showImport, setShowImport] = useState(false);

  const query = useQuery({
    queryKey: ["skills"],
    queryFn: listSkills,
  });

  const allSkills = query.data?.skills ?? [];

  const usedCategorySlugs = new Set(allSkills.map((s) => s.category_slug).filter(Boolean));
  const categories = (query.data?.categories ?? []).filter((c) => usedCategorySlugs.has(c.slug));

  const skills = allSkills
    .filter((s) => {
      if (filterCategory && s.category_slug !== filterCategory) return false;
      if (search) {
        const q = search.toLowerCase();
        const matchesPack =
          s.name.toLowerCase().includes(q) ||
          s.description?.toLowerCase().includes(q) ||
          s.tags?.some((t) => t.toLowerCase().includes(q));
        const matchesSkill = s.skills.some(
          (sk) => sk.name.toLowerCase().includes(q) || sk.description?.toLowerCase().includes(q),
        );
        if (!matchesPack && !matchesSkill) return false;
      }
      return true;
    })
    .sort((a, b) => a.name.localeCompare(b.name));

  const totalPages = Math.max(1, Math.ceil(skills.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pagedSkills = useMemo(
    () => skills.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE),
    [skills, currentPage],
  );

  const goTo = (p: number) => _setPage(Math.max(1, Math.min(p, totalPages)));

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSkillPack(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["skills"] }),
  });

  return (
    <div className="mx-auto max-w-5xl p-8">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
              <Sparkles className="h-5 w-5 text-[var(--o-accent)]" />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl font-semibold text-[var(--o-text)]">Skills</h1>
              <p className="text-sm text-[var(--o-text-secondary)]">
                Browse and import AI skill packs. Install to a project, then select in chat.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowImport(true)}
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            Import Skill
          </button>
        </div>
      </div>

      {/* Search + filters */}
      <div className="mb-6 space-y-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--o-text-tertiary)]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search skills..."
            className="o-input w-full py-2 pl-9 pr-3 text-sm"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-[var(--o-text-tertiary)] hover:text-[var(--o-text)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setFilterCategory(null)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                !filterCategory
                  ? "bg-[var(--o-accent)] text-white"
                  : "bg-[var(--o-bg-subtle)] text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
              }`}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat.slug}
                type="button"
                onClick={() => setFilterCategory(cat.slug)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  filterCategory === cat.slug
                    ? "bg-[var(--o-accent)] text-white"
                    : "bg-[var(--o-bg-subtle)] text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
                }`}
              >
                {cat.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Loading */}
      {query.isLoading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--o-text-tertiary)]" />
        </div>
      )}

      {/* Skill pack cards */}
      <div className="grid gap-4">
        {pagedSkills.map((pack) => (
          <SkillPackCard
            key={pack.id}
            pack={pack}
            onDelete={!pack.is_builtin ? () => deleteMut.mutate(pack.id) : undefined}
            isDeleting={deleteMut.isPending && deleteMut.variables === pack.id}
          />
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-6 flex items-center justify-between">
          <p className="text-xs text-[var(--o-text-tertiary)]">
            Showing {(currentPage - 1) * PAGE_SIZE + 1}–
            {Math.min(currentPage * PAGE_SIZE, skills.length)} of {skills.length} skill pack
            {skills.length !== 1 ? "s" : ""}
          </p>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => goTo(currentPage - 1)}
              disabled={currentPage <= 1}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--o-border)] text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] disabled:opacity-40 disabled:pointer-events-none"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => goTo(p)}
                className={`flex h-8 w-8 items-center justify-center rounded-lg text-xs font-medium transition-colors ${
                  p === currentPage
                    ? "bg-[var(--o-accent)] text-white"
                    : "border border-[var(--o-border)] text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
                }`}
              >
                {p}
              </button>
            ))}
            <button
              type="button"
              onClick={() => goTo(currentPage + 1)}
              disabled={currentPage >= totalPages}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--o-border)] text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] disabled:opacity-40 disabled:pointer-events-none"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Empty */}
      {skills.length === 0 && !query.isLoading && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <Sparkles className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <p className="text-sm text-[var(--o-text-secondary)]">
            {filterCategory || search ? "No skills match your search" : "No skills available"}
          </p>
        </div>
      )}

      {/* Import modal */}
      {showImport && (
        <ImportSkillModal
          onClose={() => setShowImport(false)}
          onImported={() => {
            setShowImport(false);
            qc.invalidateQueries({ queryKey: ["skills"] });
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill pack card
// ---------------------------------------------------------------------------

function SkillPackCard({
  pack,
  onDelete,
  isDeleting,
}: {
  pack: SkillPlugin;
  onDelete?: () => void;
  isDeleting?: boolean;
}) {
  return (
    <SkillPackCardBody
      pack={pack}
      showCustomBadges
      showTags
      action={
        onDelete ? (
          <button
            type="button"
            onClick={onDelete}
            disabled={isDeleting}
            className="o-btn-icon rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[color-mix(in_srgb,var(--o-danger)_10%,transparent)] hover:text-[var(--o-danger)]"
            title="Delete skill pack"
          >
            {isDeleting ? (
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

// ---------------------------------------------------------------------------
// Import from GitHub modal
// ---------------------------------------------------------------------------

function ImportSkillModal({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const [repoUrl, setRepoUrl] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);

  const importMut = useMutation({
    mutationFn: () => importSkillFromGitHub({ repo_url: repoUrl.trim() }),
    onSuccess: (data) => setResult(data),
  });

  if (result) {
    return (
      <div className="o-modal-backdrop fixed inset-0 z-50 flex items-center justify-center">
        <div className="w-full max-w-md rounded-2xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-xl">
          <div className="flex items-center justify-between border-b border-[var(--o-border)] px-5 py-3">
            <h2 className="text-sm font-semibold text-[var(--o-text)]">Import Complete</h2>
            <button
              type="button"
              onClick={onImported}
              className="rounded p-1 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-3 p-5">
            <div
              className="rounded-lg border px-3 py-2 text-xs"
              style={{
                borderColor: "color-mix(in srgb, var(--o-accent) 22%, transparent)",
                backgroundColor: "color-mix(in srgb, var(--o-accent) 6%, transparent)",
                color: "var(--o-accent)",
              }}
            >
              <p className="font-medium">
                {result.imported.length} skill pack{result.imported.length !== 1 ? "s" : ""}{" "}
                imported
                {result.total > 1 && ` (from ${result.total} in registry)`}
              </p>
            </div>

            {result.imported.length > 0 && (
              <div className="space-y-1">
                <p className="text-[11px] font-medium text-[var(--o-text-secondary)]">Imported:</p>
                {result.imported.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-2 rounded-lg bg-[var(--o-bg-subtle)] px-3 py-2"
                  >
                    <Sparkles className="h-3.5 w-3.5 text-[var(--o-accent)]" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-[var(--o-text)]">{p.name}</p>
                      <p className="text-[10px] text-[var(--o-text-tertiary)]">
                        {p.skill_count} skill{p.skill_count !== 1 ? "s" : ""}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {result.skipped.length > 0 && (
              <div className="space-y-1">
                <p className="text-[11px] font-medium text-[var(--o-text-tertiary)]">Skipped:</p>
                {result.skipped.map((s) => (
                  <p key={s} className="text-[11px] text-[var(--o-text-tertiary)]">
                    {s}
                  </p>
                ))}
              </div>
            )}

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={onImported}
                className="rounded-lg bg-[var(--o-accent)] px-4 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="o-modal-backdrop fixed inset-0 z-50 flex items-center justify-center">
      <div className="w-full max-w-md rounded-2xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-xl">
        <div className="flex items-center justify-between border-b border-[var(--o-border)] px-5 py-3">
          <div className="flex items-center gap-2">
            <Github className="h-4 w-4 text-[var(--o-text-secondary)]" />
            <h2 className="text-sm font-semibold text-[var(--o-text)]">Import Skill from GitHub</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          className="space-y-4 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (repoUrl.trim() && !importMut.isPending) importMut.mutate();
          }}
        >
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              GitHub Repository URL
            </label>
            <input
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/owner/repo or owner/repo"
              className="o-input w-full px-3 py-2 text-sm"
              autoFocus
            />
            <p className="mt-1 text-[11px] text-[var(--o-text-tertiary)]">
              Supports single skill repos (CLAUDE.md, SKILL.md) and registries (registry.yaml).
              Names and categories are auto-detected.
            </p>
          </div>

          {importMut.isError && (
            <div
              className="rounded-lg border px-3 py-2 text-xs text-[var(--o-danger)]"
              style={{
                borderColor: "color-mix(in srgb, var(--o-danger) 22%, transparent)",
                backgroundColor: "color-mix(in srgb, var(--o-danger) 6%, transparent)",
              }}
            >
              {(importMut.error as Error).message ||
                "Failed to import. Check the repo URL and try again."}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="o-btn-ghost px-4 py-2 text-xs">
              Cancel
            </button>
            <button
              type="submit"
              disabled={!repoUrl.trim() || importMut.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-4 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {importMut.isPending ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Importing...
                </>
              ) : (
                <>
                  <Github className="h-3 w-3" />
                  Import
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
