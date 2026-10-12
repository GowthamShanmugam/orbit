import { getUsageSummary, type UsageBucket, type UsageSummary } from "@/api/usage";
import { DollarSign, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

function formatUsd(n: number): string {
  if (!Number.isFinite(n) || n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function BucketCard({ label, bucket }: { label: string; bucket: UsageBucket }) {
  const cacheBits: string[] = [];
  if (bucket.cache_read_tokens > 0) {
    cacheBits.push(`${formatTokens(bucket.cache_read_tokens)} cache hit`);
  }
  if (bucket.cache_creation_tokens > 0) {
    cacheBits.push(`${formatTokens(bucket.cache_creation_tokens)} cache write`);
  }
  return (
    <div className="rounded-lg border border-[var(--o-border)] bg-[var(--o-surface)]/40 p-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--o-text-tertiary)]">
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-[var(--o-text)]">
        {formatUsd(bucket.estimated_cost_usd)}
      </p>
      <p className="mt-1 text-[11px] leading-snug text-[var(--o-text-tertiary)]">
        {formatTokens(bucket.input_tokens)} in · {formatTokens(bucket.output_tokens)} out ·{" "}
        {bucket.calls} call{bucket.calls === 1 ? "" : "s"}
      </p>
      {cacheBits.length > 0 && (
        <p className="mt-1 text-[11px] leading-snug text-[var(--o-accent)]">
          {cacheBits.join(" · ")}
        </p>
      )}
    </div>
  );
}

export default function UsagePage() {
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      setData(await getUsageSummary());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load usage");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-5xl p-8">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <DollarSign className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-[var(--o-text)]">Usage</h1>
            <p className="text-sm text-[var(--o-text-secondary)]">
              Estimated AI spend from token usage. System prompt and tools are prompt-cached
              across turns (cheaper follow-ups). Stored in the database — survives restarts and
              project deletes. Not your GCP invoice.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--o-border)] px-3 py-1.5 text-sm text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-accent)] hover:text-[var(--o-accent)] disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
          Refresh
        </button>
      </div>

      {loading && !data ? (
        <p className="mt-6 text-sm text-[var(--o-text-secondary)]">Loading…</p>
      ) : error ? (
        <p className="mt-6 text-sm text-red-400" role="alert">
          {error}
        </p>
      ) : data ? (
        <>
          <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <BucketCard label="Today" bucket={data.totals.today} />
            <BucketCard label="This month" bucket={data.totals.this_month} />
            <BucketCard label="All time" bucket={data.totals.all_time} />
          </div>

          {data.empty ? (
            <p className="mt-6 text-sm text-[var(--o-text-secondary)]">
              No AI calls recorded yet. Spend will appear here after you chat.
            </p>
          ) : (
            <>
              {data.by_model.length > 0 && (
                <div className="mt-8">
                  <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
                    By model (this month)
                  </h2>
                  <p className="mt-1 text-[11px] text-[var(--o-text-tertiary)]">
                    Totals across all calls — not a single message.
                  </p>
                  <div className="mt-2 overflow-x-auto rounded-lg border border-[var(--o-border)]">
                    <table className="w-full min-w-[28rem] text-left text-sm">
                      <thead className="border-b border-[var(--o-border)] bg-[var(--o-surface)]/60 text-[11px] uppercase tracking-wide text-[var(--o-text-tertiary)]">
                        <tr>
                          <th className="px-3 py-2 font-medium">Model</th>
                          <th className="px-3 py-2 font-medium">Cost</th>
                          <th className="px-3 py-2 font-medium">Total tokens</th>
                          <th className="px-3 py-2 font-medium">Calls</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.by_model.map((row) => (
                          <tr
                            key={row.model}
                            className="border-b border-[var(--o-border)]/60 last:border-0"
                          >
                            <td className="px-3 py-2 font-mono text-xs text-[var(--o-text)]">
                              {row.model}
                            </td>
                            <td className="px-3 py-2 tabular-nums text-[var(--o-text)]">
                              {formatUsd(row.estimated_cost_usd)}
                            </td>
                            <td className="px-3 py-2 tabular-nums text-[var(--o-text-secondary)]">
                              {formatTokens(row.input_tokens + row.output_tokens)}
                            </td>
                            <td className="px-3 py-2 tabular-nums text-[var(--o-text-secondary)]">
                              {row.calls}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {data.by_project.length > 0 && (
                <div className="mt-8">
                  <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
                    By project (this month)
                  </h2>
                  <p className="mt-1 text-[11px] text-[var(--o-text-tertiary)]">
                    Totals across all calls — not a single message.
                  </p>
                  <div className="mt-2 overflow-x-auto rounded-lg border border-[var(--o-border)]">
                    <table className="w-full min-w-[28rem] text-left text-sm">
                      <thead className="border-b border-[var(--o-border)] bg-[var(--o-surface)]/60 text-[11px] uppercase tracking-wide text-[var(--o-text-tertiary)]">
                        <tr>
                          <th className="px-3 py-2 font-medium">Project</th>
                          <th className="px-3 py-2 font-medium">Cost</th>
                          <th className="px-3 py-2 font-medium">Total tokens</th>
                          <th className="px-3 py-2 font-medium">Calls</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.by_project.map((row) => (
                          <tr
                            key={`${row.project_id ?? "gone"}-${row.project_name}`}
                            className="border-b border-[var(--o-border)]/60 last:border-0"
                          >
                            <td className="px-3 py-2 text-[var(--o-text)]">
                              {row.project_name}
                              {!row.project_id && (
                                <span className="ml-1.5 text-[10px] text-[var(--o-text-tertiary)]">
                                  deleted
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 tabular-nums text-[var(--o-text)]">
                              {formatUsd(row.estimated_cost_usd)}
                            </td>
                            <td className="px-3 py-2 tabular-nums text-[var(--o-text-secondary)]">
                              {formatTokens(row.input_tokens + row.output_tokens)}
                            </td>
                            <td className="px-3 py-2 tabular-nums text-[var(--o-text-secondary)]">
                              {row.calls}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}

          <p className="mt-6 text-[11px] leading-relaxed text-[var(--o-text-tertiary)]">
            {data.pricing_note} Provider: {data.provider}.
          </p>
        </>
      ) : null}
    </div>
  );
}
