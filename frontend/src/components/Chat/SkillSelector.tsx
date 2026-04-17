import { listProjectSkills } from "@/api/skills";
import { updateSession } from "@/api/sessions";
import { useSessionStore } from "@/stores/sessionStore";
import type { PluginSkill } from "@/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BookOpen, ChevronDown, MessageSquare, Search, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface SkillSelectorProps {
  projectId: string;
  sessionId: string;
}

export default function SkillSelector({ projectId, sessionId }: SkillSelectorProps) {
  const currentSession = useSessionStore((s) => s.currentSession);
  const setSession = useSessionStore((s) => s.setSession);
  const queryClient = useQueryClient();

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [pos, setPos] = useState<{ left: number; maxHeight: number; bottom: number } | null>(null);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const gap = 6;
    const minTop = 8;
    const spaceAbove = rect.top - gap - minTop;
    setPos({
      left: rect.left,
      bottom: window.innerHeight - rect.top + gap,
      maxHeight: Math.max(200, spaceAbove),
    });
  }, [open]);

  const { data } = useQuery({
    queryKey: ["project-skills", projectId],
    queryFn: () => listProjectSkills(projectId),
  });

  const skillPacks = useMemo(() => data?.skills ?? [], [data]);

  const allSkills: (PluginSkill & { packName: string; categorySlug?: string | null })[] = useMemo(
    () =>
      skillPacks.flatMap((pack) =>
        pack.skills
          .filter((s) => s.user_invocable)
          .map((s) => ({ ...s, packName: pack.name, categorySlug: pack.category_slug })),
      ),
    [skillPacks],
  );

  const categories = useMemo(() => {
    const usedSlugs = new Set(skillPacks.map((p) => p.category_slug).filter(Boolean));
    return (data?.categories ?? []).filter((c) => usedSlugs.has(c.slug));
  }, [data, skillPacks]);

  const currentSlug = (currentSession?.ai_config as Record<string, string> | null)?.skill ?? null;

  const currentSkill = currentSlug ? allSkills.find((s) => s.slug === currentSlug) : null;

  const selectSkill = useCallback(
    async (slug: string | null) => {
      setOpen(false);
      setSearch("");
      const prevConfig = (currentSession?.ai_config ?? {}) as Record<string, unknown>;
      const newConfig = { ...prevConfig, skill: slug };
      try {
        const updated = await updateSession(projectId, sessionId, {
          ai_config: newConfig,
        });
        setSession(updated);
        queryClient.invalidateQueries({
          queryKey: ["session", projectId, sessionId],
        });
      } catch {
        // Optimistic update on failure
      }
    },
    [projectId, sessionId, currentSession, setSession, queryClient],
  );

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(target) &&
        triggerRef.current &&
        !triggerRef.current.contains(target)
      ) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 50);
    }
  }, [open]);

  const [filterCat, setFilterCat] = useState<string | null>(null);

  const filtered = useMemo(() => {
    let result = allSkills;
    if (filterCat) {
      result = result.filter((s) => s.categorySlug === filterCat);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.packName.toLowerCase().includes(q) ||
          s.description?.toLowerCase().includes(q),
      );
    }
    return result;
  }, [allSkills, filterCat, search]);

  const groupedByPack = useMemo(() => {
    return filtered.reduce<Record<string, typeof filtered>>((acc, s) => {
      (acc[s.packName] ??= []).push(s);
      return acc;
    }, {});
  }, [filtered]);

  const dropdown =
    open && pos
      ? createPortal(
          <div
            ref={dropdownRef}
            className="fixed z-50 flex w-80 flex-col rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-lg"
            style={{
              left: pos.left,
              bottom: pos.bottom,
              height: Math.min(pos.maxHeight, 420),
              maxHeight: pos.maxHeight,
            }}
          >
            {/* Search */}
            <div className="shrink-0 border-b border-[var(--o-border)] px-3 py-2">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--o-text-tertiary)]" />
                <input
                  ref={searchRef}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search skills..."
                  className="w-full rounded-md bg-[var(--o-bg-subtle)] py-1.5 pl-7 pr-7 text-[11px] text-[var(--o-text)] placeholder-[var(--o-text-tertiary)] outline-none focus:ring-1 focus:ring-[var(--o-accent)]/40"
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-[var(--o-text-tertiary)] hover:text-[var(--o-text)]"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
            </div>

            {/* Category filter chips */}
            {categories.length > 0 && !search && (
              <div className="flex shrink-0 flex-wrap gap-1 border-b border-[var(--o-border)] px-3 py-2">
                <button
                  type="button"
                  onClick={() => setFilterCat(null)}
                  className={clsx(
                    "rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
                    !filterCat
                      ? "bg-[var(--o-accent)] text-white"
                      : "bg-[var(--o-bg-subtle)] text-[var(--o-text-tertiary)] hover:text-[var(--o-text-secondary)]",
                  )}
                >
                  All
                </button>
                {categories.map((cat) => (
                  <button
                    key={cat.slug}
                    type="button"
                    onClick={() => setFilterCat(cat.slug)}
                    className={clsx(
                      "rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
                      filterCat === cat.slug
                        ? "bg-[var(--o-accent)] text-white"
                        : "bg-[var(--o-bg-subtle)] text-[var(--o-text-tertiary)] hover:text-[var(--o-text-secondary)]",
                    )}
                  >
                    {cat.name}
                  </button>
                ))}
              </div>
            )}

            {/* General Chat (no skill) */}
            {!search && (
              <button
                type="button"
                onClick={() => selectSkill(null)}
                className={clsx(
                  "flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors",
                  !currentSlug ? "bg-[var(--o-accent-muted)]" : "hover:bg-[var(--o-bg-subtle)]",
                )}
              >
                <MessageSquare
                  className={clsx(
                    "mt-0.5 h-3.5 w-3.5 shrink-0",
                    !currentSlug ? "text-[var(--o-accent)]" : "text-[var(--o-text-tertiary)]",
                  )}
                />
                <div className="min-w-0 flex-1">
                  <p
                    className={clsx(
                      "text-[12px] font-medium",
                      !currentSlug ? "text-[var(--o-accent)]" : "text-[var(--o-text)]",
                    )}
                  >
                    General Chat
                  </p>
                  <p className="mt-0.5 text-[11px] leading-snug text-[var(--o-text-tertiary)]">
                    Free-form conversation with the AI assistant
                  </p>
                </div>
              </button>
            )}

            {/* Skill list grouped by pack */}
            <div className="min-h-0 flex-1 overflow-y-auto border-t border-[var(--o-border)] py-1">
              {Object.keys(groupedByPack).length === 0 && search && (
                <div className="px-3 py-6 text-center">
                  <p className="text-[11px] text-[var(--o-text-tertiary)]">
                    No skills match "{search}"
                  </p>
                </div>
              )}
              {Object.entries(groupedByPack).map(([packName, skills]) => (
                <div key={packName}>
                  <div className="flex items-center gap-1.5 px-3 pb-0.5 pt-2">
                    <BookOpen className="h-3 w-3 text-[var(--o-text-tertiary)]" />
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
                      {packName}
                    </span>
                  </div>
                  {skills.map((skill) => {
                    const isActive = skill.slug === currentSlug;
                    return (
                      <button
                        key={skill.slug}
                        type="button"
                        onClick={() => selectSkill(skill.slug)}
                        className={clsx(
                          "flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors",
                          isActive ? "bg-[var(--o-accent-muted)]" : "hover:bg-[var(--o-bg-subtle)]",
                        )}
                      >
                        <Sparkles
                          className={clsx(
                            "mt-0.5 h-3.5 w-3.5 shrink-0",
                            isActive ? "text-[var(--o-green)]" : "text-[var(--o-text-tertiary)]",
                          )}
                        />
                        <div className="min-w-0 flex-1">
                          <p
                            className={clsx(
                              "text-[12px] font-medium",
                              isActive ? "text-[var(--o-green)]" : "text-[var(--o-text)]",
                            )}
                          >
                            {skill.name}
                          </p>
                          {skill.description && (
                            <p className="mt-0.5 text-[11px] leading-snug text-[var(--o-text-tertiary)]">
                              {skill.description}
                            </p>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>

            {/* Clear selection */}
            {currentSlug && (
              <div className="shrink-0 border-t border-[var(--o-border)] px-1 py-1">
                <button
                  type="button"
                  onClick={() => selectSkill(null)}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[11px] font-medium text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                >
                  <X className="h-3 w-3" />
                  Clear skill selection
                </button>
              </div>
            )}

            <div className="shrink-0 border-t border-[var(--o-border)] px-3 py-1.5">
              <p className="text-[10px] text-[var(--o-text-tertiary)]">
                {allSkills.length} skill{allSkills.length !== 1 ? "s" : ""} available — select one
                to guide the AI
              </p>
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
        Skill
      </span>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-2.5 py-1 text-[11px] font-medium text-[var(--o-text-secondary)] transition-all hover:border-[var(--o-accent)]/40 hover:text-[var(--o-text)]"
      >
        {currentSkill ? (
          <>
            <Sparkles className="h-3 w-3 shrink-0 text-[var(--o-green)]" />
            <span className="max-w-[180px] truncate">{currentSkill.name}</span>
          </>
        ) : (
          <>
            <MessageSquare className="h-3 w-3 shrink-0 text-[var(--o-accent)]" />
            <span>General Chat</span>
          </>
        )}
        <ChevronDown className="h-3 w-3 shrink-0 opacity-50" />
      </button>
      {dropdown}
    </div>
  );
}
