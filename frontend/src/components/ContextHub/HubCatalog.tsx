import { listCategories, listPacks } from "@/api/contextHub";
import { useContextHubStore } from "@/stores/contextHubStore";
import type { ContextPack } from "@/types";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Database,
  FileText,
  GitBranch,
  Loader2,
  Package,
  Plus,
  Search,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

const SOURCE_ICON: Record<string, typeof Database> = {
  github_repo: GitBranch,
  gitlab_repo: GitBranch,
  jira_project: FileText,
  confluence_space: FileText,
  google_doc: FileText,
  google_drive_folder: Database,
  file_pin: FileText,
  code_snippet: FileText,
};

function PackCard({
  pack,
  onSelect,
}: {
  pack: ContextPack;
  onSelect: (id: string) => void;
}) {
  const Icon = SOURCE_ICON[pack.sources[0]?.type] ?? Package;
  return (
    <button
      type="button"
      onClick={() => onSelect(pack.id)}
      className="o-card-hover group flex flex-col gap-3 rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-5 text-left"
      style={{ backgroundImage: "var(--o-gradient-card)" }}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--o-bg-subtle)] text-[var(--o-accent)]">
          {pack.icon ? (
            <span className="text-lg">{pack.icon}</span>
          ) : (
            <Icon className="h-5 w-5" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-[var(--o-text)] group-hover:text-[var(--o-accent)]">
            {pack.name}
          </p>
          {pack.category && (
            <span className="mt-0.5 inline-block rounded-full bg-[var(--o-bg-subtle)] px-2 py-0.5 text-[10px] font-medium text-[var(--o-text-secondary)]">
              {pack.category}
            </span>
          )}
        </div>
      </div>
      <p className="line-clamp-2 text-sm leading-relaxed text-[var(--o-text-secondary)]">
        {pack.description || "No description"}
      </p>
      <div className="flex items-center gap-4 text-xs text-[var(--o-border-subtle)]">
        <span>{pack.repo_count} repos</span>
        <span>{pack.sources.length} sources</span>
        <span>v{pack.version}</span>
      </div>
    </button>
  );
}

export default function HubCatalog() {
  const navigate = useNavigate();
  const { searchQuery, setSearchQuery, selectedCategory, setSelectedCategory } =
    useContextHubStore();
  const [debouncedSearch, setDebouncedSearch] = useState(searchQuery);

  const packsQuery = useQuery({
    queryKey: ["packs", debouncedSearch, selectedCategory],
    queryFn: () =>
      listPacks({
        search: debouncedSearch || undefined,
        category: selectedCategory || undefined,
      }),
  });

  const categoriesQuery = useQuery({
    queryKey: ["pack-categories"],
    queryFn: listCategories,
  });

  const packs = packsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];

  function handleSearch(val: string) {
    setSearchQuery(val);
    setDebouncedSearch(val);
  }

  return (
    <div className="mx-auto max-w-6xl p-8">
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--o-text)]">
            Context Hub
          </h1>
          <p className="mt-1 text-sm text-[var(--o-text-secondary)]">
            Browse and install context packs to supercharge your AI sessions
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate("/hub/create")}
          className="o-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm"
        >
          <Plus className="h-4 w-4" />
          Create Pack
        </button>
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--o-border-subtle)]" />
          <input
            type="text"
            placeholder="Search packs by name or description..."
            value={searchQuery}
            onChange={(e) => handleSearch(e.target.value)}
            className="o-input w-full py-2.5 pl-10 pr-3 text-sm"
          />
        </div>
      </div>

      {categories.length > 0 && (
        <div className="mb-6 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setSelectedCategory(null)}
            className={clsx(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              selectedCategory === null
                ? "bg-[var(--o-accent)]/15 text-[var(--o-accent)]"
                : "bg-[var(--o-bg-subtle)] text-[var(--o-text-secondary)] hover:text-[var(--o-text)]",
            )}
          >
            All
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() =>
                setSelectedCategory(selectedCategory === cat ? null : cat)
              }
              className={clsx(
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                selectedCategory === cat
                  ? "bg-[var(--o-accent)]/15 text-[var(--o-accent)]"
                  : "bg-[var(--o-bg-subtle)] text-[var(--o-text-secondary)] hover:text-[var(--o-text)]",
              )}
            >
              {cat}
            </button>
          ))}
        </div>
      )}

      {packsQuery.isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-[var(--o-text-secondary)]" />
        </div>
      ) : packs.length === 0 ? (
        <div className="o-empty">
          <Package className="mx-auto mb-3 h-10 w-10 text-[var(--o-border-subtle)]" />
          <p className="text-sm font-medium text-[var(--o-text-secondary)]">
            No packs found
          </p>
          <p className="mt-1 text-xs text-[var(--o-border-subtle)]">
            {searchQuery || selectedCategory
              ? "Try adjusting your search or filters"
              : "Create the first context pack to get started"}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {packs.map((pack) => (
            <PackCard
              key={pack.id}
              pack={pack}
              onSelect={(id) => navigate(`/hub/${id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
