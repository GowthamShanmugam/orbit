import { BookOpen, Github, Sparkles } from "lucide-react";
import React, { useState, type ReactNode } from "react";

interface SkillInfo {
  slug: string;
  name: string;
  description?: string | null;
  user_invocable?: boolean;
}

interface SkillPackData {
  name: string;
  description?: string | null;
  is_builtin?: boolean;
  category_name?: string | null;
  tags?: string[] | null;
  skills: SkillInfo[];
}

interface Props {
  pack: SkillPackData;
  showCustomBadges?: boolean;
  showTags?: boolean;
  action?: ReactNode;
}

export default function SkillPackCardBody({ pack, showCustomBadges, showTags, action }: Props) {
  const [expanded, setExpanded] = useState(false);
  const invocableSkills = pack.skills.filter((s) => s.user_invocable);

  return (
    <div className="rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-5 transition-all hover:border-[var(--o-border-hover)] hover:shadow-sm">
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
          <BookOpen className="h-5 w-5 text-[var(--o-accent)]" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h3 className="text-sm font-semibold text-[var(--o-text)]">{pack.name}</h3>
            <span className="rounded bg-[var(--o-pastel-lavender)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--o-pastel-lavender-fg)]">
              Skill Pack
            </span>
            {pack.is_builtin && (
              <span className="rounded bg-[var(--o-pastel-mint)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--o-pastel-mint-fg)]">
                Built-in
              </span>
            )}
            {showCustomBadges && !pack.is_builtin && (
              <span className="inline-flex items-center gap-1 rounded bg-[var(--o-pastel-rose)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--o-pastel-rose-fg)]">
                <Github className="h-2.5 w-2.5" />
                Custom
              </span>
            )}
            {pack.category_name && (
              <span className="text-[10px] text-[var(--o-text-tertiary)]">
                {pack.category_name}
              </span>
            )}
            <span className="text-[11px] text-[var(--o-text-tertiary)]">
              {invocableSkills.length} skill{invocableSkills.length !== 1 ? "s" : ""}
            </span>
          </div>

          {pack.description && (
            <p className="mt-1 text-xs text-[var(--o-text-secondary)] line-clamp-2">
              {pack.description}
            </p>
          )}

          {invocableSkills.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {invocableSkills.slice(0, expanded ? undefined : 5).map((s) => (
                <span
                  key={s.slug}
                  className="inline-flex items-center gap-1 rounded-md bg-[var(--o-bg-subtle)] px-2 py-1 text-[11px] text-[var(--o-text-secondary)]"
                  title={s.description ?? undefined}
                >
                  <Sparkles className="h-3 w-3 text-[var(--o-accent)]" />
                  {s.name}
                </span>
              ))}
              {!expanded && (
                <button
                  type="button"
                  onClick={() => setExpanded(true)}
                  className="rounded-md bg-[var(--o-accent-muted)] px-2 py-1 text-[11px] font-medium text-[var(--o-accent)] hover:underline"
                >
                  {invocableSkills.length > 5
                    ? `+${invocableSkills.length - 5} more`
                    : "more"}
                </button>
              )}
            </div>
          )}

          {expanded && invocableSkills.length > 0 && (
            <div className="mt-3 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] p-3">
              <div className="grid grid-cols-[minmax(auto,max-content)_1fr] gap-x-3 gap-y-1.5">
                {invocableSkills.map((s) => (
                  <React.Fragment key={s.slug}>
                    <span className="rounded bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[10px] font-medium leading-snug text-[var(--o-text-secondary)]">
                      {s.name}
                    </span>
                    <span className="py-0.5 text-xs leading-snug text-[var(--o-text-secondary)]">
                      {s.description ?? s.name}
                    </span>
                  </React.Fragment>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="mt-2 text-[11px] font-medium text-[var(--o-accent)] hover:underline"
              >
                Show less
              </button>
            </div>
          )}

          {showTags && pack.tags && pack.tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {pack.tags.slice(0, 4).map((tag) => (
                <span
                  key={tag}
                  className="rounded bg-[var(--o-bg)] px-1.5 py-0.5 text-[10px] text-[var(--o-text-tertiary)]"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {action}
      </div>
    </div>
  );
}
