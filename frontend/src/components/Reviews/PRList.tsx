import { listContextSources } from "@/api/context";
import { listPulls, type PRListItem } from "@/api/reviews";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ChevronRight,
  Clock,
  GitMerge,
  GitPullRequest,
  Loader2,
  User,
} from "lucide-react";
import { useMemo, useState } from "react";

function parseGitHubUrl(url: string): { owner: string; repo: string } | null {
  const m = url.match(/github\.com[/:]([^/]+)\/([^/.]+)/);
  if (!m) return null;
  return { owner: m[1], repo: m[2] };
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso));
  } catch {
    return iso;
  }
}

interface PRListProps {
  projectId: string;
  onSelectPR: (pr: PRListItem, owner: string, repo: string) => void;
}

export default function PRList({ projectId, onSelectPR }: PRListProps) {
  const [stateFilter, setStateFilter] = useState<"open" | "closed" | "all">("open");

  const sourcesQuery = useQuery({
    queryKey: ["context-sources", projectId],
    queryFn: () => listContextSources(projectId),
    enabled: Boolean(projectId),
  });

  const githubRepos = useMemo(() => {
    const sources = sourcesQuery.data ?? [];
    const repos: { owner: string; repo: string; name: string }[] = [];
    for (const src of sources) {
      if (src.type === "github_repo" && src.url) {
        const parsed = parseGitHubUrl(src.url);
        if (parsed) repos.push({ ...parsed, name: src.name });
      }
    }
    return repos;
  }, [sourcesQuery.data]);

  const [selectedRepo, setSelectedRepo] = useState<number>(0);
  const activeRepo = githubRepos[selectedRepo];

  const prsQuery = useQuery({
    queryKey: ["pulls", projectId, activeRepo?.owner, activeRepo?.repo, stateFilter],
    queryFn: () => listPulls(projectId, activeRepo!.owner, activeRepo!.repo, stateFilter),
    enabled: Boolean(activeRepo),
  });

  const pulls = prsQuery.data ?? [];

  if (sourcesQuery.isLoading) {
    return (
      <div className="flex justify-center py-12 text-[var(--o-text-secondary)]">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (githubRepos.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-8 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[var(--o-pastel-mint)]">
          <GitPullRequest className="h-6 w-6 text-[var(--o-pastel-mint-fg)]" />
        </div>
        <h3 className="mt-3 text-sm font-semibold text-[var(--o-text)]">No GitHub repositories</h3>
        <p className="mt-1 text-xs text-[var(--o-text-secondary)]">
          Add a GitHub repository context source to this project to review pull requests.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {githubRepos.length > 1 && (
          <select
            value={selectedRepo}
            onChange={(e) => setSelectedRepo(Number(e.target.value))}
            className="rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-1.5 text-sm text-[var(--o-text)] focus:border-[var(--o-accent)] focus:outline-none"
          >
            {githubRepos.map((r, i) => (
              <option key={`${r.owner}/${r.repo}`} value={i}>
                {r.owner}/{r.repo}
              </option>
            ))}
          </select>
        )}
        {githubRepos.length === 1 && (
          <span className="text-sm font-medium text-[var(--o-text)]">
            {activeRepo?.owner}/{activeRepo?.repo}
          </span>
        )}

        <div className="flex gap-0.5 rounded-lg border border-[var(--o-border)] p-0.5">
          {(["open", "closed", "all"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStateFilter(s)}
              className={clsx(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                stateFilter === s
                  ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                  : "text-[var(--o-text-secondary)] hover:text-[var(--o-text)]",
              )}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {prsQuery.isLoading ? (
        <div className="flex justify-center py-12 text-[var(--o-text-secondary)]">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : pulls.length === 0 ? (
        <div className="rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-6 text-center text-sm text-[var(--o-text-secondary)]">
          No {stateFilter} pull requests found.
        </div>
      ) : (
        <div className="space-y-2">
          {pulls.map((pr) => (
            <PRRow
              key={pr.number}
              pr={pr}
              onClick={() => onSelectPR(pr, activeRepo!.owner, activeRepo!.repo)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function PRRow({ pr, onClick }: { pr: PRListItem; onClick: () => void }) {
  const isMerged = pr.state === "closed" && (pr as unknown as Record<string, unknown>).merged_at;
  const author = pr.user?.login ?? pr.author ?? "unknown";
  const labels = (pr.labels ?? []).map((l) => (typeof l === "string" ? l : l.name));

  return (
    <button
      type="button"
      onClick={onClick}
      className="group w-full rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] px-4 py-3 text-left transition-shadow hover:shadow-md"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0">
          {isMerged ? (
            <GitMerge className="h-4 w-4 text-[var(--o-pastel-lavender-fg)]" />
          ) : pr.state === "open" ? (
            <GitPullRequest className="h-4 w-4 text-[var(--o-pastel-mint-fg)]" />
          ) : (
            <GitPullRequest className="h-4 w-4 text-[var(--o-text-tertiary)]" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-[var(--o-text)]">{pr.title}</span>
            <span className="shrink-0 text-xs text-[var(--o-text-tertiary)]">#{pr.number}</span>
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-2.5 text-[11px] text-[var(--o-text-tertiary)]">
            <span className="inline-flex items-center gap-1">
              <User className="h-3 w-3" />
              {author}
            </span>
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {timeAgo(pr.updated_at)}
            </span>
            {pr.draft && (
              <span className="rounded-full bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--o-text-tertiary)]">
                Draft
              </span>
            )}
            {pr.additions != null && (
              <span className="text-[var(--o-pastel-mint-fg)]">+{pr.additions}</span>
            )}
            {pr.deletions != null && (
              <span className="text-[var(--o-pastel-rose-fg)]">-{pr.deletions}</span>
            )}
          </div>

          {labels.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {labels.map((l) => (
                <span
                  key={l}
                  className="rounded-full bg-[var(--o-pastel-sky)] px-2 py-0.5 text-[10px] font-medium text-[var(--o-pastel-sky-fg)]"
                >
                  {l}
                </span>
              ))}
            </div>
          )}
        </div>

        <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-[var(--o-text-tertiary)] transition-transform group-hover:translate-x-0.5" />
      </div>
    </button>
  );
}
