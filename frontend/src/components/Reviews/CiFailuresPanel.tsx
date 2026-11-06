import {
  debugCiJob,
  listCiJobs,
  type CiDebugResult,
  type CiJob,
  type ReviewProvider,
} from "@/api/reviews";
import { useQuery } from "@tanstack/react-query";
import {
  Bug,
  Check,
  ExternalLink,
  Loader2,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

type Props = {
  projectId: string;
  prNumber: number;
  owner: string;
  repo: string;
  provider: ReviewProvider;
  /** Report failed-job count so the parent tab can show a badge. */
  onFailedCount?: (count: number) => void;
};

function debugCacheKey(
  projectId: string,
  provider: ReviewProvider,
  owner: string,
  repo: string,
  prNumber: number,
): string {
  return `orbit-ci-debug:${projectId}:${provider}:${owner}/${repo}:${prNumber}`;
}

function loadCachedResults(key: string): Record<string, CiDebugResult> {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return parsed as Record<string, CiDebugResult>;
  } catch {
    return {};
  }
}

function saveCachedResults(key: string, results: Record<string, CiDebugResult>) {
  try {
    sessionStorage.setItem(key, JSON.stringify(results));
  } catch {
    // quota / private mode — ignore
  }
}

export default function CiFailuresPanel({
  projectId,
  prNumber,
  owner,
  repo,
  provider,
  onFailedCount,
}: Props) {
  const cacheKey = useMemo(
    () => debugCacheKey(projectId, provider, owner, repo, prNumber),
    [projectId, provider, owner, repo, prNumber],
  );
  const [debuggingId, setDebuggingId] = useState<string | null>(null);
  const [debugError, setDebugError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, CiDebugResult>>(() =>
    loadCachedResults(cacheKey),
  );
  const [showAll, setShowAll] = useState(false);

  // Re-hydrate when switching to another PR (same component instance is rare, but safe).
  useEffect(() => {
    setResults(loadCachedResults(cacheKey));
  }, [cacheKey]);

  useEffect(() => {
    saveCachedResults(cacheKey, results);
  }, [cacheKey, results]);

  const query = useQuery({
    queryKey: ["ci-jobs", projectId, provider, owner, repo, prNumber],
    queryFn: () => listCiJobs(projectId, prNumber, owner, repo, provider),
    refetchInterval: (q) => {
      const status = q.state.data?.pipeline_status;
      if (
        status &&
        ["running", "pending", "created", "waiting_for_resource", "preparing"].includes(
          status,
        )
      ) {
        return 15_000;
      }
      return false;
    },
  });

  const jobs = query.data?.jobs ?? [];
  const failed = jobs.filter((j) => j.failure && !j.allow_failure);
  const visible = showAll ? jobs : failed.length > 0 ? failed : jobs.slice(0, 8);
  const failedCount = query.data?.failed_count ?? failed.length;

  useEffect(() => {
    if (!query.isSuccess) return;
    onFailedCount?.(failedCount);
  }, [query.isSuccess, failedCount, onFailedCount]);

  const handleDebug = useCallback(
    async (job: CiJob) => {
      setDebuggingId(job.id);
      setDebugError(null);
      try {
        const result = await debugCiJob(
          projectId,
          prNumber,
          job.id,
          owner,
          repo,
          provider,
        );
        setResults((prev) => ({ ...prev, [job.id]: result }));
      } catch (err: unknown) {
        setDebugError(err instanceof Error ? err.message : "Debug failed");
      } finally {
        setDebuggingId(null);
      }
    },
    [projectId, prNumber, owner, repo, provider],
  );

  const handleDebugAllFailed = useCallback(async () => {
    for (const job of failed) {
      // Sequential to avoid slamming GitLab + AI.
      // eslint-disable-next-line no-await-in-loop
      await handleDebug(job);
    }
  }, [failed, handleDebug]);

  if (query.isLoading) {
    return (
      <div className="px-4 py-6 text-[12px] text-[var(--o-text-tertiary)]">
        <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />
        Loading CI jobs…
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="px-4 py-6 text-[12px] text-[var(--o-danger)]">
        Could not load CI:{" "}
        {query.error instanceof Error ? query.error.message : "unknown error"}
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div className="px-4 py-6 text-[12px] text-[var(--o-text-tertiary)]">
        No CI jobs found for this {provider === "gitlab" ? "MR" : "PR"}.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--o-bg)]">
      <div className="flex shrink-0 items-center gap-2 border-b border-[var(--o-border)] px-4 py-2">
        <Bug className="h-3.5 w-3.5 text-[var(--o-text-secondary)]" />
        <span className="text-[12px] font-semibold text-[var(--o-text)]">
          {failedCount > 0 ? (
            <span className="text-[var(--o-pastel-rose-fg)]">{failedCount} failed</span>
          ) : (
            <span className="text-[var(--o-pastel-mint-fg)]">All green</span>
          )}
        </span>
        {query.data?.pipeline_status && (
          <span className="text-[11px] text-[var(--o-text-tertiary)]">
            pipeline {query.data.pipeline_status}
            {query.data.pipeline_id ? ` #${query.data.pipeline_id}` : ""}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-auto px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          {failed.length > 1 && (
            <button
              type="button"
              onClick={() => void handleDebugAllFailed()}
              disabled={debuggingId !== null}
              className="rounded-md border border-[var(--o-border)] px-2 py-1 text-[10px] font-medium text-[var(--o-text)] hover:border-[var(--o-accent)] disabled:opacity-40"
            >
              Debug all failed
            </button>
          )}
          {failed.length > 0 && jobs.length > failed.length && (
            <button
              type="button"
              onClick={() => setShowAll((s) => !s)}
              className="text-[10px] text-[var(--o-text-tertiary)] hover:text-[var(--o-accent)]"
            >
              {showAll ? "Show failed only" : `Show all jobs (${jobs.length})`}
            </button>
          )}
          {query.data?.pipeline_web_url && (
            <a
              href={query.data.pipeline_web_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-[10px] text-[var(--o-accent)] hover:underline"
            >
              Pipeline <ExternalLink className="h-2.5 w-2.5" />
            </a>
          )}
        </div>

        {debugError && (
          <p className="text-[11px] text-[var(--o-danger)]">{debugError}</p>
        )}

        <ul className="space-y-1">
          {visible.map((job) => {
            const result = results[job.id];
            const isDebugging = debuggingId === job.id;
            return (
              <li
                key={job.id}
                className="rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] px-2.5 py-2"
              >
                <div className="flex items-center gap-2">
                  {job.failure && !job.allow_failure ? (
                    <XCircle className="h-3.5 w-3.5 shrink-0 text-[var(--o-pastel-rose-fg)]" />
                  ) : (
                    <Check className="h-3.5 w-3.5 shrink-0 text-[var(--o-pastel-mint-fg)]" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-medium text-[var(--o-text)]">
                      {job.name}
                      {job.stage ? (
                        <span className="ml-1.5 font-normal text-[10px] text-[var(--o-text-tertiary)]">
                          {job.stage}
                        </span>
                      ) : null}
                    </p>
                    <p className="text-[10px] text-[var(--o-text-tertiary)]">
                      {job.status}
                      {typeof job.duration === "number"
                        ? ` · ${Math.round(job.duration)}s`
                        : ""}
                    </p>
                  </div>
                  {job.web_url && (
                    <a
                      href={job.web_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded p-1 text-[var(--o-text-tertiary)] hover:text-[var(--o-accent)]"
                      title="Open job"
                    >
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                  {(job.failure || provider === "github") && (
                    <button
                      type="button"
                      disabled={isDebugging}
                      onClick={() => void handleDebug(job)}
                      className="inline-flex items-center gap-1 rounded-md bg-[var(--o-accent)] px-2 py-1 text-[10px] font-medium text-white hover:opacity-90 disabled:opacity-40"
                    >
                      {isDebugging ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Bug className="h-3 w-3" />
                      )}
                      {result ? "Re-debug" : "Debug"}
                    </button>
                  )}
                </div>

                {result && (
                  <div className="mt-2 rounded-md border border-[var(--o-border)]/70 bg-[var(--o-bg)] px-2.5 py-2 text-[11px]">
                    <p className="font-semibold text-[var(--o-text)]">
                      {result.diagnosis.root_cause}
                    </p>
                    {result.diagnosis.where && (
                      <p className="mt-0.5 font-mono text-[10px] text-[var(--o-accent)]">
                        {result.diagnosis.where}
                      </p>
                    )}
                    {result.diagnosis.summary && (
                      <p className="mt-1 leading-relaxed text-[var(--o-text-secondary)]">
                        {result.diagnosis.summary}
                      </p>
                    )}
                    {result.diagnosis.evidence && (
                      <pre className="mt-1.5 max-h-24 overflow-auto rounded bg-[var(--o-bg-subtle)] p-1.5 font-mono text-[10px] text-[var(--o-text-tertiary)] whitespace-pre-wrap">
                        {result.diagnosis.evidence}
                      </pre>
                    )}
                    <p className="mt-1 text-[10px] text-[var(--o-text-tertiary)]">
                      {result.used_test_report ? "test report · " : ""}
                      log tail
                      {result.used_artifacts && result.used_artifacts.length > 0
                        ? ` · artifacts: ${result.used_artifacts.slice(0, 4).join(", ")}${
                            result.used_artifacts.length > 4 ? "…" : ""
                          }`
                        : provider === "gitlab"
                          ? " · no useful artifacts"
                          : ""}
                      {result.used_repo_reads && result.used_repo_reads.length > 0
                        ? ` · code: ${result.used_repo_reads.slice(0, 3).join(", ")}${
                            result.used_repo_reads.length > 3 ? "…" : ""
                          }`
                        : result.used_checkout
                          ? " · checkout ready (unused)"
                          : ""}
                      {provider === "github"
                        ? " (GitHub: summary only — Actions artifacts later)"
                        : ""}
                    </p>
                    {result.artifacts_note ? (
                      <p className="mt-0.5 text-[10px] text-[var(--o-warning)]">
                        {result.artifacts_note}
                      </p>
                    ) : null}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
