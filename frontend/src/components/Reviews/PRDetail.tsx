import { createPRComment, getPullComments, getPullDetail, getPullDiff, getPullFiles, replyToComment } from "@/api/reviews";
import type { PRListItem } from "@/api/reviews";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Clock,
  ExternalLink,
  GitMerge,
  GitPullRequest,
  Loader2,
  User,
  XCircle,
} from "lucide-react";
import { useCallback } from "react";
import DiffViewer, { type AddCommentParams, type DiffFile } from "./DiffViewer";

interface PRDetailProps {
  projectId: string;
  pr: PRListItem;
  owner: string;
  repo: string;
  onBack: () => void;
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

export default function PRDetail({ projectId, pr, owner, repo, onBack }: PRDetailProps) {
  const queryClient = useQueryClient();

  const detailQuery = useQuery({
    queryKey: ["pr-detail", projectId, owner, repo, pr.number],
    queryFn: () => getPullDetail(projectId, pr.number, owner, repo),
  });

  const commitId: string =
    pr.head?.sha ??
    ((detailQuery.data?.head as Record<string, unknown> | undefined)?.sha as string | undefined) ??
    "";

  const filesQuery = useQuery({
    queryKey: ["pr-files", projectId, owner, repo, pr.number],
    queryFn: () => getPullFiles(projectId, pr.number, owner, repo),
  });

  const diffQuery = useQuery({
    queryKey: ["pr-diff", projectId, owner, repo, pr.number],
    queryFn: () => getPullDiff(projectId, pr.number, owner, repo),
  });

  const commentsQuery = useQuery({
    queryKey: ["pr-comments", projectId, owner, repo, pr.number],
    queryFn: () => getPullComments(projectId, pr.number, owner, repo),
  });

  const handleAddComment = useCallback(
    async (params: AddCommentParams) => {
      if (!commitId) throw new Error("Cannot comment: PR commit SHA not available");
      await createPRComment(projectId, pr.number, owner, repo, {
        path: params.path,
        line: params.line,
        side: params.side,
        body: params.body,
        commit_id: commitId,
        start_line: params.startLine,
        start_side: params.startSide,
      });
      await queryClient.invalidateQueries({
        queryKey: ["pr-comments", projectId, owner, repo, pr.number],
      });
    },
    [projectId, pr.number, owner, repo, commitId, queryClient],
  );

  const handleReplyComment = useCallback(
    async (commentId: number, body: string) => {
      await replyToComment(projectId, pr.number, commentId, owner, repo, body);
      await queryClient.invalidateQueries({
        queryKey: ["pr-comments", projectId, owner, repo, pr.number],
      });
    },
    [projectId, pr.number, owner, repo, queryClient],
  );

  const diffFiles: DiffFile[] = (() => {
    const raw = filesQuery.data;
    if (!raw) return [];
    const arr = Array.isArray(raw) ? raw : (raw as Record<string, unknown>).files;
    if (!Array.isArray(arr)) return [];
    return arr.map((f: Record<string, unknown>) => ({
      filename: String(f.filename ?? f.path ?? "unknown"),
      status: String(f.status ?? "modified"),
      additions: Number(f.additions ?? 0),
      deletions: Number(f.deletions ?? 0),
      patch: typeof f.patch === "string" ? f.patch : undefined,
    }));
  })();

  const existingComments = (() => {
    const raw = commentsQuery.data;
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    const arr = (raw as Record<string, unknown>).comments;
    if (Array.isArray(arr)) return arr;
    return [];
  })();

  const totalAdditions = diffFiles.reduce((s, f) => s + f.additions, 0);
  const totalDeletions = diffFiles.reduce((s, f) => s + f.deletions, 0);
  const isMerged = pr.state === "closed" && (pr as unknown as Record<string, unknown>).merged_at;
  const author = pr.user?.login ?? pr.author ?? "unknown";
  const headBranch = pr.head?.ref ?? "";
  const baseBranch = pr.base?.ref ?? "";

  return (
    <div className="flex h-full flex-col">
      {/* PR Header */}
      <div className="shrink-0 border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-4 py-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onBack}
            className="rounded-lg p-1 text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>

          <div className="shrink-0">
            {isMerged ? (
              <GitMerge className="h-5 w-5 text-[var(--o-pastel-lavender-fg)]" />
            ) : pr.state === "open" ? (
              <GitPullRequest className="h-5 w-5 text-[var(--o-pastel-mint-fg)]" />
            ) : (
              <XCircle className="h-5 w-5 text-[var(--o-pastel-rose-fg)]" />
            )}
          </div>

          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold text-[var(--o-text)]">
              {pr.title}
              <span className="ml-2 text-xs font-normal text-[var(--o-text-tertiary)]">
                #{pr.number}
              </span>
            </h2>
            <div className="mt-0.5 flex flex-wrap items-center gap-2.5 text-[11px] text-[var(--o-text-tertiary)]">
              <span className="inline-flex items-center gap-1">
                <User className="h-3 w-3" />
                {author}
              </span>
              {headBranch && (
                <span>
                  <code className="rounded bg-[var(--o-bg-subtle)] px-1 py-0.5 text-[10px]">
                    {headBranch}
                  </code>
                  {" → "}
                  <code className="rounded bg-[var(--o-bg-subtle)] px-1 py-0.5 text-[10px]">
                    {baseBranch}
                  </code>
                </span>
              )}
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                Updated {timeAgo(pr.updated_at)}
              </span>
              <span>
                <span className="text-[var(--o-pastel-mint-fg)]">+{totalAdditions}</span>
                {" "}
                <span className="text-[var(--o-pastel-rose-fg)]">-{totalDeletions}</span>
                {" · "}
                {diffFiles.length} file{diffFiles.length !== 1 ? "s" : ""}
              </span>
              {pr.html_url && (
                <a
                  href={pr.html_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--o-accent)] hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  <ExternalLink className="h-3 w-3" />
                  GitHub
                </a>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Diff with inline comments */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {filesQuery.isLoading ? (
          <div className="flex justify-center py-12 text-[var(--o-text-secondary)]">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <DiffViewer
            files={diffFiles}
            rawDiff={typeof diffQuery.data === "string" ? diffQuery.data : undefined}
            existingComments={existingComments}
            onAddComment={commitId ? handleAddComment : undefined}
            onReplyComment={handleReplyComment}
          />
        )}
      </div>
    </div>
  );
}
