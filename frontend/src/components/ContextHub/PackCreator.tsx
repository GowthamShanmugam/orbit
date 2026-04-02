import { createPack, getPack, updatePack } from "@/api/contextHub";
import type { ContextSourceType, PackVisibility } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Loader2,
  Plus,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMatch, useNavigate } from "react-router-dom";

const VISIBILITY_OPTIONS: { value: PackVisibility; label: string }[] = [
  { value: "organization", label: "Organization" },
  { value: "public", label: "Public" },
  { value: "personal", label: "Personal" },
];

const SOURCE_TYPES: { value: ContextSourceType; label: string }[] = [
  { value: "github_repo", label: "GitHub Repo" },
  { value: "gitlab_repo", label: "GitLab Repo" },
  { value: "jira_project", label: "Jira Project" },
  { value: "confluence_space", label: "Confluence Space" },
  { value: "google_doc", label: "Google Doc" },
  { value: "google_drive_folder", label: "Google Drive Folder" },
  { value: "file_pin", label: "Pinned File" },
  { value: "code_snippet", label: "Code Snippet" },
];

interface SourceDraft {
  key: number;
  type: ContextSourceType;
  name: string;
  url: string;
}

let nextKey = 1;

export default function PackCreator() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const editMatch = useMatch("/hub/:packId/edit");
  const packId = editMatch?.params.packId;
  const isEdit = Boolean(packId);
  const formHydrated = useRef(false);

  const packQuery = useQuery({
    queryKey: ["pack", packId],
    queryFn: () => getPack(packId!),
    enabled: isEdit && Boolean(packId),
  });

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [icon, setIcon] = useState("");
  const [visibility, setVisibility] = useState<PackVisibility>("organization");
  const [maintainerTeam, setMaintainerTeam] = useState("");
  const [sources, setSources] = useState<SourceDraft[]>([]);

  useEffect(() => {
    const p = packQuery.data;
    if (!p || !isEdit || formHydrated.current) return;
    setName(p.name);
    setDescription(p.description ?? "");
    setCategory(p.category ?? "");
    setIcon(p.icon ?? "");
    setVisibility(p.visibility);
    setMaintainerTeam(p.maintainer_team ?? "");
    setSources(
      p.sources.map((s) => ({
        key: nextKey++,
        type: s.type as ContextSourceType,
        name: s.name,
        url: s.url ?? "",
      })),
    );
    formHydrated.current = true;
  }, [packQuery.data, isEdit]);

  const createMut = useMutation({
    mutationFn: () =>
      createPack({
        name: name.trim(),
        description: description.trim() || undefined,
        category: category.trim() || undefined,
        icon: icon.trim() || undefined,
        visibility,
        maintainer_team: maintainerTeam.trim() || undefined,
        sources: sources
          .filter((s) => s.name.trim())
          .map((s) => ({
            type: s.type,
            name: s.name.trim(),
            url: s.url.trim() || undefined,
          })),
      }),
    onSuccess: (pack) => {
      queryClient.invalidateQueries({ queryKey: ["packs"] });
      navigate(`/hub/${pack.id}`);
    },
  });

  const updateMut = useMutation({
    mutationFn: () =>
      updatePack(packId!, {
        name: name.trim(),
        description: description.trim() || undefined,
        category: category.trim() || undefined,
        icon: icon.trim() || undefined,
        visibility,
        maintainer_team: maintainerTeam.trim() || undefined,
      }),
    onSuccess: (pack) => {
      queryClient.invalidateQueries({ queryKey: ["packs"] });
      queryClient.invalidateQueries({ queryKey: ["pack", pack.id] });
      navigate(`/hub/${pack.id}`);
    },
  });

  function addSource() {
    setSources([
      ...sources,
      { key: nextKey++, type: "github_repo", name: "", url: "" },
    ]);
  }

  function updateSource(key: number, field: keyof SourceDraft, value: string) {
    setSources(
      sources.map((s) => (s.key === key ? { ...s, [field]: value } : s)),
    );
  }

  function removeSource(key: number) {
    setSources(sources.filter((s) => s.key !== key));
  }

  const inputCls = "o-input w-full px-3 py-2 text-sm";

  if (isEdit && packQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--o-text-secondary)]" />
      </div>
    );
  }

  if (isEdit && packQuery.isError) {
    return (
      <div className="mx-auto max-w-3xl p-8 text-sm text-[var(--o-danger)]">
        Could not load pack for editing.
      </div>
    );
  }

  const pending = createMut.isPending || updateMut.isPending;

  return (
    <div className="mx-auto max-w-3xl p-8">
      <button
        type="button"
        onClick={() =>
          navigate(isEdit && packId ? `/hub/${packId}` : "/hub")
        }
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-[var(--o-text-secondary)] transition-colors hover:text-[var(--o-accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        {isEdit ? "Back to pack" : "Back to catalog"}
      </button>

      <h1 className="mb-6 text-2xl font-semibold text-[var(--o-text)]">
        {isEdit ? "Edit Context Pack" : "Create Context Pack"}
      </h1>

      {isEdit && (
        <p className="mb-6 text-sm text-[var(--o-text-secondary)]">
          Update name, description, visibility, and maintainer. Sources are listed
          for reference; to add or remove sources, use the Context Hub API or future
          pack source management on the pack detail page.
        </p>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim() || pending) return;
          if (isEdit) updateMut.mutate();
          else createMut.mutate();
        }}
        className="space-y-6"
      >
        <div className="o-panel p-5">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]">
            Pack Details
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label
                htmlFor="pack-name"
                className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
              >
                Name *
              </label>
              <input
                id="pack-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={inputCls}
                placeholder="e.g. OpenShift Data Science"
                autoFocus
              />
            </div>
            <div className="sm:col-span-2">
              <label
                htmlFor="pack-desc"
                className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
              >
                Description
              </label>
              <textarea
                id="pack-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className={`${inputCls} resize-none`}
                placeholder="Describe what this pack covers..."
              />
            </div>
            <div>
              <label
                htmlFor="pack-cat"
                className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
              >
                Category
              </label>
              <input
                id="pack-cat"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className={inputCls}
                placeholder="e.g. AI/ML, Platform"
              />
            </div>
            <div>
              <label
                htmlFor="pack-icon"
                className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
              >
                Icon (emoji)
              </label>
              <input
                id="pack-icon"
                value={icon}
                onChange={(e) => setIcon(e.target.value)}
                className={inputCls}
                placeholder="e.g. 🚀"
              />
            </div>
            <div>
              <label
                htmlFor="pack-vis"
                className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
              >
                Visibility
              </label>
              <select
                id="pack-vis"
                value={visibility}
                onChange={(e) =>
                  setVisibility(e.target.value as PackVisibility)
                }
                className={inputCls}
              >
                {VISIBILITY_OPTIONS.map((v) => (
                  <option key={v.value} value={v.value}>
                    {v.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="pack-team"
                className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
              >
                Maintainer Team
              </label>
              <input
                id="pack-team"
                value={maintainerTeam}
                onChange={(e) => setMaintainerTeam(e.target.value)}
                className={inputCls}
                placeholder="e.g. ODH Team"
              />
            </div>
          </div>
        </div>

        <div className="o-panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]">
              Sources ({sources.length})
            </h2>
            {!isEdit && (
              <button
                type="button"
                onClick={addSource}
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--o-bg-subtle)] px-3 py-1.5 text-xs font-medium text-[var(--o-text)] ring-1 ring-[var(--o-border)] transition-all hover:ring-[var(--o-accent)]/40"
              >
                <Plus className="h-3.5 w-3.5" />
                Add Source
              </button>
            )}
          </div>

          {sources.length === 0 ? (
            <div className="o-empty py-8 text-sm text-[var(--o-text-secondary)]">
              {isEdit
                ? "This pack has no sources."
                : 'No sources added yet. Click "Add Source" above.'}
            </div>
          ) : (
            <div className="space-y-3">
              {sources.map((src) => (
                <div
                  key={src.key}
                  className="flex flex-wrap items-start gap-2 rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] p-3"
                >
                  <select
                    value={src.type}
                    onChange={(e) =>
                      updateSource(
                        src.key,
                        "type",
                        e.target.value,
                      )
                    }
                    disabled={isEdit}
                    className="w-40 rounded-md border border-[var(--o-border)] bg-[var(--o-bg-raised)] px-2 py-1.5 text-xs text-[var(--o-text)] outline-none disabled:opacity-70"
                  >
                    {SOURCE_TYPES.map((st) => (
                      <option key={st.value} value={st.value}>
                        {st.label}
                      </option>
                    ))}
                  </select>
                  <input
                    placeholder="Name"
                    value={src.name}
                    onChange={(e) =>
                      updateSource(src.key, "name", e.target.value)
                    }
                    readOnly={isEdit}
                    className="min-w-0 flex-1 rounded-md border border-[var(--o-border)] bg-[var(--o-bg-raised)] px-2 py-1.5 text-xs text-[var(--o-text)] outline-none placeholder:text-[var(--o-text-tertiary)] read-only:opacity-80"
                  />
                  <input
                    placeholder="URL (optional)"
                    value={src.url}
                    onChange={(e) =>
                      updateSource(src.key, "url", e.target.value)
                    }
                    readOnly={isEdit}
                    className="min-w-0 flex-1 rounded-md border border-[var(--o-border)] bg-[var(--o-bg-raised)] px-2 py-1.5 text-xs text-[var(--o-text)] outline-none placeholder:text-[var(--o-text-tertiary)] read-only:opacity-80"
                  />
                  {!isEdit && (
                    <button
                      type="button"
                      onClick={() => removeSource(src.key)}
                      className="rounded p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-danger)]"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {createMut.isError && (
          <p className="text-sm text-[var(--o-danger)]">
            Failed to create pack. Please try again.
          </p>
        )}
        {updateMut.isError && (
          <p className="text-sm text-[var(--o-danger)]">
            Failed to update pack. Please try again.
          </p>
        )}

        <div className="flex justify-end gap-3">
          <button
            type="button"
            disabled={pending}
            onClick={() => navigate(isEdit && packId ? `/hub/${packId}` : "/hub")}
            className="o-btn-ghost px-4 py-2 text-sm"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!name.trim() || pending}
            className="o-btn-success inline-flex items-center gap-2 px-5 py-2 text-sm disabled:opacity-50"
          >
            {pending && (
              <Loader2 className="h-4 w-4 animate-spin" />
            )}
            {isEdit ? "Save changes" : "Create Pack"}
          </button>
        </div>
      </form>
    </div>
  );
}
