import {
  addPendingReviewComment,
  createDirectReview,
  createPRComment,
  deleteComment,
  discardReview,
  editComment,
  getPendingReview,
  getPullComments,
  getPullDetail,
  getPullDiff,
  getPullFiles,
  replyToComment,
  startPendingReview,
  submitReview,
  type PRListItem,
  type ReviewEvent,
} from "@/api/reviews";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowLeft,
  Clock,
  ExternalLink,
  GitMerge,
  GitPullRequest,
  Loader2,
  MessageSquare,
  Trash2,
  User,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import DiffViewer, { type AddCommentParams, type DiffFile } from "./DiffViewer";

interface LocalPendingComment {
  id: string;
  githubCommentId: number | null;
  path: string;
  line: number;
  side: "LEFT" | "RIGHT";
  body: string;
  user?: { login: string };
  isPending: true;
  startLine?: number;
  startSide?: "LEFT" | "RIGHT";
}

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

  const [pendingReviewNodeId, setPendingReviewNodeId] = useState<string | null>(null);
  const [pendingReviewDbId, setPendingReviewDbId] = useState<number | null>(null);
  const [pendingComments, setPendingComments] = useState<LocalPendingComment[]>([]);
  const [showSubmitDialog, setShowSubmitDialog] = useState(false);
  const pendingCommentCount = pendingComments.length;

  useEffect(() => {
    let cancelled = false;
    getPendingReview(projectId, pr.number, owner, repo).then((info) => {
      if (cancelled || !info.pending || !info.review_node_id) return;
      setPendingReviewNodeId(info.review_node_id);
      setPendingReviewDbId(info.review_id ?? null);
      const restored: LocalPendingComment[] = (info.comments ?? []).map((c) => ({
        id: `pending-${c.id}`,
        githubCommentId: c.id,
        path: c.path,
        line: c.line ?? 0,
        side: (c.side as "LEFT" | "RIGHT") ?? "RIGHT",
        body: c.body,
        user: c.user,
        isPending: true,
      }));
      setPendingComments(restored);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [projectId, pr.number, owner, repo]);

  const detailQuery = useQuery({
    queryKey: ["pr-detail", projectId, owner, repo, pr.number],
    queryFn: () => getPullDetail(projectId, pr.number, owner, repo),
  });

  const currentUser: string =
    (detailQuery.data?.user as Record<string, unknown> | undefined)?.login as string ?? "";

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

  const invalidateComments = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["pr-comments", projectId, owner, repo, pr.number] }),
    [queryClient, projectId, owner, repo, pr.number],
  );

  const handleAddComment = useCallback(
    async (params: AddCommentParams) => {
      if (!commitId) throw new Error("Cannot comment: PR commit SHA not available");
      await createPRComment(projectId, pr.number, owner, repo, {
        path: params.path, line: params.line, side: params.side,
        body: params.body, commit_id: commitId,
        start_line: params.startLine, start_side: params.startSide,
      });
      await invalidateComments();
    },
    [projectId, pr.number, owner, repo, commitId, invalidateComments],
  );

  const handleStartReview = useCallback(
    async (params: AddCommentParams) => {
      if (!commitId) throw new Error("Cannot comment: PR commit SHA not available");
      const result = await startPendingReview(projectId, pr.number, owner, repo, {
        path: params.path, line: params.line, side: params.side,
        body: params.body, commit_id: commitId,
        start_line: params.startLine, start_side: params.startSide,
      });
      setPendingReviewNodeId(result.review_node_id);
      setPendingReviewDbId(result.review_id ?? null);
      const ghId = result.comment_id ?? null;
      setPendingComments([{
        id: ghId ? `pending-${ghId}` : `pending-${Date.now()}`,
        githubCommentId: ghId,
        path: params.path, line: params.line, side: params.side,
        body: params.body, isPending: true,
        user: currentUser ? { login: currentUser } : undefined,
        startLine: params.startLine, startSide: params.startSide,
      }]);
    },
    [projectId, pr.number, owner, repo, commitId, currentUser],
  );

  const handleAddReviewComment = useCallback(
    async (params: AddCommentParams) => {
      if (!commitId || !pendingReviewNodeId) throw new Error("No pending review");
      const result = await addPendingReviewComment(projectId, pr.number, owner, repo, {
        review_node_id: pendingReviewNodeId,
        path: params.path, line: params.line, side: params.side,
        body: params.body, commit_id: commitId,
        start_line: params.startLine, start_side: params.startSide,
      });
      const ghId = result.comment_id ?? null;
      setPendingComments((prev) => [...prev, {
        id: ghId ? `pending-${ghId}` : `pending-${Date.now()}`,
        githubCommentId: ghId,
        path: params.path, line: params.line, side: params.side,
        body: params.body, isPending: true,
        user: currentUser ? { login: currentUser } : undefined,
        startLine: params.startLine, startSide: params.startSide,
      }]);
    },
    [projectId, pr.number, owner, repo, commitId, pendingReviewNodeId, currentUser],
  );

  const handleSubmitReview = useCallback(
    async (event: ReviewEvent, body: string) => {
      if (pendingReviewNodeId) {
        await submitReview(projectId, pr.number, owner, repo, pendingReviewNodeId, event, body);
      } else {
        await createDirectReview(projectId, pr.number, owner, repo, event, body);
      }
      setPendingReviewNodeId(null);
      setPendingReviewDbId(null);
      setPendingComments([]);
      setShowSubmitDialog(false);
      await invalidateComments();
    },
    [projectId, pr.number, owner, repo, pendingReviewNodeId, invalidateComments],
  );

  const handleDiscardReview = useCallback(async () => {
    if (!pendingReviewNodeId) return;
    await discardReview(projectId, pr.number, owner, repo, pendingReviewNodeId, pendingReviewDbId);
    setPendingReviewNodeId(null);
    setPendingReviewDbId(null);
    setPendingComments([]);
  }, [projectId, pr.number, owner, repo, pendingReviewNodeId, pendingReviewDbId]);

  const handleReplyComment = useCallback(
    async (commentId: number, body: string) => {
      await replyToComment(projectId, pr.number, commentId, owner, repo, body);
      await invalidateComments();
    },
    [projectId, pr.number, owner, repo, invalidateComments],
  );

  const handleDeleteComment = useCallback(
    async (commentId: number | string) => {
      if (typeof commentId === "string" && commentId.startsWith("pending-")) {
        const pending = pendingComments.find((c) => c.id === commentId);
        if (pending?.githubCommentId) {
          await deleteComment(projectId, pr.number, pending.githubCommentId, owner, repo);
        }
        const remaining = pendingComments.filter((c) => c.id !== commentId);
        setPendingComments(remaining);
        if (remaining.length === 0 && pendingReviewNodeId) {
          await discardReview(projectId, pr.number, owner, repo, pendingReviewNodeId, pendingReviewDbId);
          setPendingReviewNodeId(null);
          setPendingReviewDbId(null);
        }
        return;
      }
      await deleteComment(projectId, pr.number, Number(commentId), owner, repo);
      await invalidateComments();
    },
    [projectId, pr.number, owner, repo, invalidateComments, pendingComments, pendingReviewNodeId, pendingReviewDbId],
  );

  const handleEditComment = useCallback(
    async (commentId: number | string, body: string) => {
      if (typeof commentId === "string" && commentId.startsWith("pending-")) {
        const pending = pendingComments.find((c) => c.id === commentId);
        if (pending?.githubCommentId) {
          await editComment(projectId, pr.number, pending.githubCommentId, owner, repo, body);
        }
        setPendingComments((prev) =>
          prev.map((c) => (c.id === commentId ? { ...c, body } : c)),
        );
        return;
      }
      await editComment(projectId, pr.number, Number(commentId), owner, repo, body);
      await invalidateComments();
    },
    [projectId, pr.number, owner, repo, invalidateComments, pendingComments],
  );

  const diffFiles: DiffFile[] = (() => {
    const raw = filesQuery.data;
    if (!raw) return [];
    let arr = Array.isArray(raw) ? raw : (raw as Record<string, unknown>).files;
    if (typeof arr === "string") {
      try { arr = JSON.parse(arr); } catch { return []; }
    }
    if (!Array.isArray(arr)) return [];
    return arr.map((f: Record<string, unknown>) => ({
      filename: String(f.filename ?? f.path ?? "unknown"),
      status: String(f.status ?? "modified"),
      additions: Number(f.additions ?? 0),
      deletions: Number(f.deletions ?? 0),
      patch: typeof f.patch === "string" ? f.patch : undefined,
    }));
  })();

  const serverComments = useMemo(() => {
    const raw = commentsQuery.data;
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    const arr = (raw as Record<string, unknown>).comments;
    if (Array.isArray(arr)) return arr;
    return [];
  }, [commentsQuery.data]);

  const allComments = useMemo(
    () => [...serverComments, ...pendingComments],
    [serverComments, pendingComments],
  );

  const totalAdditions = diffFiles.reduce((s, f) => s + f.additions, 0);
  const totalDeletions = diffFiles.reduce((s, f) => s + f.deletions, 0);
  const isMerged = pr.state === "closed" && (pr as unknown as Record<string, unknown>).merged_at;
  const author = pr.user?.login ?? pr.author ?? "unknown";
  const headBranch = pr.head?.ref ?? "";
  const baseBranch = pr.base?.ref ?? "";
  const isOwnPR = Boolean(currentUser && currentUser === author);

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

          {pr.state === "open" && (
            <button
              type="button"
              onClick={() => setShowSubmitDialog(true)}
              className={clsx(
                "ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90",
                pendingCommentCount > 0 ? "bg-[var(--o-pastel-mint-fg)]" : "bg-[var(--o-accent)]",
              )}
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Submit review
              {pendingCommentCount > 0 && (
                <span className="ml-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-white/25 px-1 text-[10px] font-bold">
                  {pendingCommentCount}
                </span>
              )}
            </button>
          )}
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
            existingComments={allComments}
            currentUser={currentUser}
            hasPendingReview={Boolean(pendingReviewNodeId)}
            pendingCommentCount={pendingCommentCount}
            onAddComment={commitId ? handleAddComment : undefined}
            onStartReview={commitId ? handleStartReview : undefined}
            onAddReviewComment={pendingReviewNodeId ? handleAddReviewComment : undefined}
            onReplyComment={handleReplyComment}
            onEditComment={handleEditComment}
            onDeleteComment={handleDeleteComment}
          />
        )}
      </div>

      {showSubmitDialog && (
        <SubmitReviewDialog
          pendingCount={pendingCommentCount}
          hasPendingReview={Boolean(pendingReviewNodeId)}
          isOwnPR={isOwnPR}
          onSubmit={handleSubmitReview}
          onDiscard={handleDiscardReview}
          onClose={() => setShowSubmitDialog(false)}
        />
      )}
    </div>
  );
}

function SubmitReviewDialog({
  pendingCount,
  hasPendingReview,
  isOwnPR,
  onSubmit,
  onDiscard,
  onClose,
}: {
  pendingCount: number;
  hasPendingReview: boolean;
  isOwnPR: boolean;
  onSubmit: (event: ReviewEvent, body: string) => Promise<void>;
  onDiscard: () => Promise<void>;
  onClose: () => void;
}) {
  const [body, setBody] = useState("");
  const [event, setEvent] = useState<ReviewEvent>("COMMENT");
  const [submitting, setSubmitting] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = submitting || discarding;

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(event, body.trim());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit review");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDiscard = async () => {
    setDiscarding(true);
    setError(null);
    try {
      await onDiscard();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to discard review");
    } finally {
      setDiscarding(false);
    }
  };

  const options: { value: ReviewEvent; label: string; desc: string; color: string; disabled?: boolean; disabledHint?: string }[] = [
    { value: "COMMENT", label: "Comment", desc: "Submit general feedback without explicit approval.", color: "text-[var(--o-text)]" },
    { value: "APPROVE", label: "Approve", desc: "Submit feedback and approve merging these changes.", color: "text-[var(--o-pastel-mint-fg)]", disabled: isOwnPR, disabledHint: "Pull request authors can\u2019t approve their own pull requests." },
    { value: "REQUEST_CHANGES", label: "Request changes", desc: "Submit feedback that must be addressed before merging.", color: "text-[var(--o-pastel-rose-fg)]", disabled: isOwnPR, disabledHint: "Pull request authors can\u2019t request changes on their own pull requests." },
  ];

  return (
    <div
      className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}
    >
      <div className="w-full max-w-md rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--o-border)] px-5 py-3">
          <h3 className="text-sm font-semibold text-[var(--o-text)]">
            Submit review
          </h3>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded p-1 text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {hasPendingReview && pendingCount > 0 && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-300/40 bg-amber-50 px-3 py-2 dark:border-amber-700/30 dark:bg-amber-950/30">
              <MessageSquare className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
              <span className="flex-1 text-[11px] font-medium text-amber-800 dark:text-amber-200">
                {pendingCount} pending comment{pendingCount !== 1 ? "s" : ""} will be submitted
              </span>
            </div>
          )}

          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--o-text-secondary)]">
              Review summary (optional)
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Leave a comment on this pull request..."
              rows={3}
              className="w-full resize-y rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-xs text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none"
            />
          </div>

          <div className="space-y-2">
            {options.map((opt) => (
              <label
                key={opt.value}
                className={clsx(
                  "flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors",
                  opt.disabled
                    ? "cursor-not-allowed opacity-40 border-[var(--o-border)]"
                    : "cursor-pointer",
                  !opt.disabled && event === opt.value
                    ? "border-[var(--o-accent)] bg-[var(--o-accent-muted)]"
                    : !opt.disabled ? "border-[var(--o-border)] hover:border-[var(--o-text-tertiary)]" : "",
                )}
              >
                <input
                  type="radio"
                  name="review-event"
                  value={opt.value}
                  checked={event === opt.value}
                  onChange={() => !opt.disabled && setEvent(opt.value)}
                  disabled={opt.disabled}
                  className="mt-0.5 accent-[var(--o-accent)]"
                />
                <div>
                  <span className={clsx("text-xs font-semibold", opt.color)}>{opt.label}</span>
                  <p className="mt-0.5 text-[11px] text-[var(--o-text-secondary)]">{opt.desc}</p>
                  {opt.disabled && opt.disabledHint && (
                    <p className="mt-1 text-[10px] italic text-amber-600 dark:text-amber-400">{opt.disabledHint}</p>
                  )}
                </div>
              </label>
            ))}
          </div>

          {error && (
            <div className="rounded-md bg-[var(--o-pastel-rose)] px-3 py-2 text-[11px] text-[var(--o-pastel-rose-fg)]">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[var(--o-border)] px-5 py-3">
          <div>
            {hasPendingReview && (
              <button
                type="button"
                onClick={() => void handleDiscard()}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-[var(--o-danger,#dc2626)] transition-colors hover:bg-[var(--o-pastel-rose)] disabled:opacity-50"
              >
                <Trash2 className="h-3 w-3" />
                {discarding ? "Discarding..." : "Discard review"}
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-lg px-3 py-1.5 text-xs text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={busy || (event === "COMMENT" && pendingCount === 0 && !body.trim())}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50",
                event === "APPROVE" && "bg-[var(--o-pastel-mint-fg)]",
                event === "REQUEST_CHANGES" && "bg-[var(--o-pastel-rose-fg)]",
                event === "COMMENT" && "bg-[var(--o-accent)]",
              )}
            >
              {submitting && <Loader2 className="h-3 w-3 animate-spin" />}
              Submit review
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
