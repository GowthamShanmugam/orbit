import type { Project } from "@/types";
import clsx from "clsx";
import { Building2, Globe, User } from "lucide-react";

/** Public vs private, with legacy personal/organization hint when relevant. */
export default function ProjectWorkspaceBadge({
  project,
  className,
  compact = false,
  presentation = "pill",
}: {
  project: Pick<
    Project,
    "visibility" | "workspace_type" | "organization_name"
  >;
  className?: string;
  /** Smaller padding for dense headers */
  compact?: boolean;
  /** `pill` = bordered chip (default). `inline` = muted one-line meta for dense lists (e.g. project catalog). */
  presentation?: "pill" | "inline";
}) {
  const pad = compact
    ? "px-2.5 py-1 text-xs"
    : "px-2 py-0.5 text-[11px]";

  const vis = project.visibility ?? "private";

  if (presentation === "inline") {
    if (vis === "public") {
      const tip = "Visible to everyone signed in";
      return (
        <span
          className={clsx(
            "inline-flex min-w-0 max-w-full items-center gap-1.5 text-xs text-[var(--o-text-tertiary)]",
            className,
          )}
          title={tip}
        >
          <Globe className="h-3.5 w-3.5 shrink-0 text-emerald-600/85 dark:text-emerald-400/90" />
          <span className="min-w-0 truncate font-medium text-[var(--o-text-secondary)]">
            Public
          </span>
        </span>
      );
    }
    const isOrg = project.workspace_type === "organization";
    if (isOrg) {
      const org = project.organization_name?.trim();
      const label = org ? `Private · ${org}` : "Private · Organization";
      return (
        <span
          className={clsx(
            "inline-flex min-w-0 max-w-full items-center gap-1.5 text-xs text-[var(--o-text-tertiary)]",
            className,
          )}
          title={label}
        >
          <Building2 className="h-3.5 w-3.5 shrink-0 text-sky-600/85 dark:text-sky-400/90" />
          <span className="min-w-0 truncate font-medium text-[var(--o-text-secondary)]">
            {label}
          </span>
        </span>
      );
    }
    const tip = "Personal workspace";
    return (
      <span
        className={clsx(
          "inline-flex min-w-0 max-w-full items-center gap-1.5 text-xs text-[var(--o-text-tertiary)]",
          className,
        )}
        title={tip}
      >
        <User className="h-3.5 w-3.5 shrink-0 opacity-75" />
        <span className="min-w-0 truncate font-medium text-[var(--o-text-secondary)]">
          Private · Personal
        </span>
      </span>
    );
  }

  if (vis === "public") {
    return (
      <span
        className={clsx(
          "inline-flex max-w-full items-center gap-1.5 rounded-md border border-emerald-500/35 bg-emerald-500/10 font-semibold uppercase tracking-wide text-emerald-800 dark:text-emerald-200",
          pad,
          className,
        )}
      >
        <Globe className="h-3 w-3 shrink-0" />
        Public
      </span>
    );
  }

  const isOrg = project.workspace_type === "organization";
  if (isOrg) {
    return (
      <span
        className={clsx(
          "inline-flex max-w-full items-center gap-1.5 rounded-md border border-sky-500/30 bg-sky-500/8 font-semibold uppercase tracking-wide text-sky-800 dark:text-sky-200",
          pad,
          className,
        )}
      >
        <Building2 className="h-3 w-3 shrink-0" />
        <span className="min-w-0 truncate">
          Private
          {project.organization_name?.trim() ? (
            <span className="font-normal opacity-90">
              {" "}
              · {project.organization_name.trim()}
            </span>
          ) : null}
        </span>
      </span>
    );
  }

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border border-[var(--o-border)] bg-[var(--o-bg-subtle)] font-semibold uppercase tracking-wide text-[var(--o-text-secondary)]",
        pad,
        className,
      )}
    >
      <User className="h-3 w-3" />
      Private
    </span>
  );
}
