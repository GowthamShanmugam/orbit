import { getPullFileContent, getPullFlowChart, type ReviewProvider } from "@/api/reviews";
import MermaidBlock from "@/components/Markdown/MermaidBlock";
import MarkdownView from "@/components/Markdown/MarkdownView";
import { prepareCommentMarkdown } from "@/components/Reviews/prepareCommentMarkdown";
import clsx from "clsx";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  GitBranch,
  Info,
  Loader2,
  Maximize2,
  MessageSquare,
  Minimize2,
  MoreHorizontal,
  Pencil,
  Plus,
  Reply,
  Trash2,
  X,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface DiffFile {
  filename: string;
  status: string;
  additions: number;
  deletions: number;
  patch?: string;
}

const EXPAND_STEP = 20;

type DiffLine = {
  type: "add" | "remove" | "context";
  content: string;
  oldLine?: number;
  newLine?: number;
  expanded?: boolean;
};

type DiffHunk = {
  header: string;
  lines: DiffLine[];
};

/** How many lines revealed from each edge of a hidden gap. */
type GapReveal = { top: number; bottom: number };

type GapInfo = {
  index: number;
  start: number;
  end: number;
};

interface InlineComment {
  id: number | string;
  path: string;
  line?: number;
  side?: string;
  body: string;
  user?: { login: string };
  created_at?: string;
  in_reply_to_id?: number;
  pull_request_review_id?: number;
  /** Locally-tracked pending comment, not yet visible on GitHub */
  isPending?: boolean;
}

interface LineAnchor {
  lineNo: number;
  side: "LEFT" | "RIGHT";
  type: "add" | "remove" | "context";
  globalIdx: number;
}

export interface AddCommentParams {
  path: string;
  line: number;
  side: "LEFT" | "RIGHT";
  body: string;
  startLine?: number;
  startSide?: "LEFT" | "RIGHT";
}

interface DiffViewerProps {
  files: DiffFile[];
  rawDiff?: string;
  existingComments?: InlineComment[];
  currentUser?: string;
  hasPendingReview?: boolean;
  pendingCommentCount?: number;
  projectId?: string;
  prNumber?: number;
  owner?: string;
  repo?: string;
  provider?: ReviewProvider;
  onAddComment?: (params: AddCommentParams) => Promise<void>;
  onStartReview?: (params: AddCommentParams) => Promise<void>;
  onAddReviewComment?: (params: AddCommentParams) => Promise<void>;
  onReplyComment?: (commentId: number, body: string) => Promise<void>;
  onEditComment?: (commentId: number | string, body: string) => Promise<void>;
  onDeleteComment?: (commentId: number | string) => Promise<void>;
}

function parsePatch(patch: string): DiffHunk[] {
  const hunks: DiffHunk[] = [];
  const hunkParts = patch.split(/^(@@[^@]+@@.*$)/m).filter(Boolean);

  for (let i = 0; i < hunkParts.length; i++) {
    const part = hunkParts[i];
    if (!part.startsWith("@@")) continue;

    const header = part;
    const body = hunkParts[i + 1] ?? "";
    const match = header.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    let oldLine = match ? parseInt(match[1], 10) : 1;
    let newLine = match ? parseInt(match[2], 10) : 1;

    const lines: DiffLine[] = [];
    for (const raw of body.split("\n")) {
      if (raw === "") continue;
      if (raw.startsWith("+")) {
        lines.push({ type: "add", content: raw.slice(1), newLine: newLine++ });
      } else if (raw.startsWith("-")) {
        lines.push({ type: "remove", content: raw.slice(1), oldLine: oldLine++ });
      } else {
        lines.push({
          type: "context",
          content: raw.startsWith(" ") ? raw.slice(1) : raw,
          oldLine: oldLine++,
          newLine: newLine++,
        });
      }
    }

    hunks.push({ header, lines });
    i++;
  }

  return hunks;
}

function hunkNewRange(hunk: DiffHunk): { first: number | null; last: number | null } {
  const news = hunk.lines
    .map((l) => l.newLine)
    .filter((n): n is number => typeof n === "number");
  return {
    first: news.length ? Math.min(...news) : null,
    last: news.length ? Math.max(...news) : null,
  };
}

/**
 * Gaps of unchanged new-file lines: index i is above hunk i; index hunks.length is after the last.
 * Between-hunk / leading gaps need only hunk ranges; trailing needs fileLen.
 */
function computeGaps(
  hunks: DiffHunk[],
  fileLen: number | null,
): (GapInfo | null)[] {
  const ranges = hunks.map(hunkNewRange);
  const gaps: (GapInfo | null)[] = [];

  for (let i = 0; i < hunks.length; i++) {
    const prevLast = i === 0 ? 0 : (ranges[i - 1].last ?? 0);
    const thisFirst = ranges[i].first;
    if (thisFirst == null) {
      gaps.push(null);
      continue;
    }
    const start = prevLast + 1;
    const end = thisFirst - 1;
    gaps.push(start <= end ? { index: i, start, end } : null);
  }

  const last = [...ranges].reverse().find((r) => r.last != null)?.last ?? null;
  if (fileLen != null && last != null && last < fileLen) {
    gaps.push({ index: hunks.length, start: last + 1, end: fileLen });
  } else {
    gaps.push(null);
  }
  return gaps;
}

function clampGapReveal(gap: GapInfo, reveal: GapReveal | undefined): {
  top: number;
  bottom: number;
  remaining: number;
  size: number;
} {
  const size = gap.end - gap.start + 1;
  let top = Math.max(0, Math.min(reveal?.top ?? 0, size));
  let bottom = Math.max(0, Math.min(reveal?.bottom ?? 0, size - top));
  return { top, bottom, remaining: size - top - bottom, size };
}

function contextLinesFromFile(
  fileLines: string[],
  start: number,
  end: number,
): DiffLine[] {
  const lines: DiffLine[] = [];
  for (let n = start; n <= end; n++) {
    if (n < 1 || n > fileLines.length) continue;
    lines.push({
      type: "context",
      content: fileLines[n - 1] ?? "",
      newLine: n,
      expanded: true,
    });
  }
  return lines;
}

function lineSide(type: "add" | "remove" | "context"): "LEFT" | "RIGHT" {
  return type === "remove" ? "LEFT" : "RIGHT";
}

function lineNumber(line: { type: string; oldLine?: number; newLine?: number }): number {
  return line.type === "remove" ? (line.oldLine ?? 0) : (line.newLine ?? 0);
}

type CommentThread = { root: InlineComment; replies: InlineComment[] };

function groupThreads(comments: InlineComment[]): CommentThread[] {
  const threads: CommentThread[] = [];
  const threadMap = new Map<number | string, CommentThread>();
  for (const comment of comments) {
    if (comment.in_reply_to_id != null && threadMap.has(comment.in_reply_to_id)) {
      const thread = threadMap.get(comment.in_reply_to_id)!;
      thread.replies.push(comment);
      threadMap.set(comment.id, thread);
    } else {
      const thread = { root: comment, replies: [] as InlineComment[] };
      threads.push(thread);
      threadMap.set(comment.id, thread);
    }
  }
  return threads;
}

function FileStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const cfg =
    s === "added"
      ? { bg: "var(--o-pastel-mint)", fg: "var(--o-pastel-mint-fg)", label: "A" }
      : s === "removed"
        ? { bg: "var(--o-pastel-rose)", fg: "var(--o-pastel-rose-fg)", label: "D" }
        : s === "modified" || s === "changed"
          ? { bg: "var(--o-pastel-peach)", fg: "var(--o-pastel-peach-fg)", label: "M" }
          : s === "renamed"
            ? { bg: "var(--o-pastel-sky)", fg: "var(--o-pastel-sky-fg)", label: "R" }
            : { bg: "var(--o-bg-subtle)", fg: "var(--o-text-secondary)", label: s[0]?.toUpperCase() ?? "?" };

  return (
    <span
      className="inline-flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold"
      style={{ backgroundColor: cfg.bg, color: cfg.fg }}
    >
      {cfg.label}
    </span>
  );
}

function GapExpander({
  remaining,
  loading,
  /** Grow toward the next hunk (↑) or from the previous hunk (↓). One direction per gap. */
  edge,
  onExpand,
}: {
  remaining: number | null;
  loading: boolean;
  edge: "top" | "bottom";
  onExpand: (edge: "top" | "bottom" | "all") => void;
}) {
  const step = remaining == null ? EXPAND_STEP : Math.min(EXPAND_STEP, remaining);
  if (remaining === 0) return null;
  const Icon = edge === "bottom" ? ChevronUp : ChevronDown;
  return (
    <div className="flex items-center gap-2 border-y border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-3 py-1 font-sans text-[11px] text-[var(--o-text-tertiary)]">
      <button
        type="button"
        disabled={loading}
        onClick={() => onExpand(edge)}
        title={
          edge === "bottom"
            ? `Show ${step} lines above`
            : `Show ${step} lines below`
        }
        className="inline-flex items-center justify-center rounded p-1 text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-raised)] hover:text-[var(--o-text)] disabled:opacity-50"
      >
        <Icon className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        disabled={loading}
        onClick={() => onExpand(edge)}
        className="min-w-0 truncate text-left hover:text-[var(--o-text)] disabled:opacity-50"
      >
        {remaining == null
          ? "Show more context"
          : remaining <= step
            ? `Show ${remaining} hidden line${remaining === 1 ? "" : "s"}`
            : `Show ${step} of ${remaining} hidden lines`}
      </button>
      {remaining != null && remaining > step && (
        <button
          type="button"
          disabled={loading}
          onClick={() => onExpand("all")}
          className="rounded px-1.5 py-0.5 text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-raised)] hover:text-[var(--o-text)] disabled:opacity-50"
        >
          Expand all
        </button>
      )}
      {loading && <Loader2 className="h-3 w-3 animate-spin" />}
    </div>
  );
}

function CommentForm({
  hasPendingReview,
  onSingleComment,
  onStartReview,
  onAddReviewComment,
  onCancel,
}: {
  hasPendingReview: boolean;
  onSingleComment?: (body: string) => Promise<void>;
  onStartReview?: (body: string) => Promise<void>;
  onAddReviewComment?: (body: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { textareaRef.current?.focus(); }, []);

  const handleAction = async (key: string, action: (body: string) => Promise<void>) => {
    if (!text.trim() || activeAction) return;
    setActiveAction(key);
    setError(null);
    try {
      await action(text.trim());
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to post comment";
      setError(msg);
    } finally {
      setActiveAction(null);
    }
  };

  return (
    <div className="border border-[var(--o-border)] rounded-lg bg-[var(--o-bg-raised)] p-3 my-1">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => { setText(e.target.value); setError(null); }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
        }}
        placeholder="Write a comment..."
        rows={3}
        className="w-full resize-y rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 font-sans text-xs text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none"
      />
      {error && (
        <div className="mt-1.5 flex items-start gap-1.5 rounded-md bg-[var(--o-pastel-rose)] px-2.5 py-1.5 text-[11px] text-[var(--o-pastel-rose-fg)]">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      <div className="mt-2 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={!!activeAction}
          className="rounded-md px-3 py-1.5 text-xs text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
        >
          Cancel
        </button>

        {hasPendingReview ? (
          <button
            type="button"
            onClick={() => onAddReviewComment && void handleAction("add-review", onAddReviewComment)}
            disabled={!text.trim() || !!activeAction}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--o-accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {activeAction === "add-review" && <Loader2 className="h-3 w-3 animate-spin" />}
            Add review comment
          </button>
        ) : (
          <>
            {onSingleComment && (
              <button
                type="button"
                onClick={() => void handleAction("single", onSingleComment)}
                disabled={!text.trim() || !!activeAction}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-1.5 text-xs font-medium text-[var(--o-text)] hover:bg-[var(--o-bg-subtle)] disabled:opacity-50"
              >
                {activeAction === "single" && <Loader2 className="h-3 w-3 animate-spin" />}
                Add single comment
              </button>
            )}
            {onStartReview && (
              <button
                type="button"
                onClick={() => void handleAction("start-review", onStartReview)}
                disabled={!text.trim() || !!activeAction}
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--o-pastel-mint-fg)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {activeAction === "start-review" && <Loader2 className="h-3 w-3 animate-spin" />}
                Start a review
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function InlineThread({
  thread,
  currentUser,
  onReply,
  onEdit,
  onDelete,
}: {
  thread: { root: InlineComment; replies: InlineComment[] };
  currentUser?: string;
  onReply?: (commentId: number, body: string) => Promise<void>;
  onEdit?: (commentId: number | string, body: string) => Promise<void>;
  onDelete?: (commentId: number | string) => Promise<void>;
}) {
  const [showReply, setShowReply] = useState(false);
  const { root, replies } = thread;
  const lastId = replies.length > 0 ? Number(replies[replies.length - 1].id) : Number(root.id);

  const isPending = root.isPending;

  return (
    <div className={clsx(
      "my-1 rounded-lg border px-3 py-2",
      isPending
        ? "border-amber-300/50 bg-amber-50/50 dark:border-amber-700/30 dark:bg-amber-950/20"
        : "border-[var(--o-border)] bg-[var(--o-bg-raised)]",
    )}>
      <CommentBubble
        comment={root}
        currentUser={currentUser}
        onEdit={onEdit}
        onDelete={onDelete}
      />

      {replies.map((r) => (
        <div key={r.id} className="mt-1.5 border-l-2 border-[var(--o-border)] pl-2.5">
          <CommentBubble
            comment={r}
            currentUser={currentUser}
            onEdit={onEdit}
            onDelete={onDelete}
            isReply
          />
        </div>
      ))}

      {onReply && !showReply && (
        <button
          type="button"
          onClick={() => setShowReply(true)}
          className="mt-1.5 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-accent)]"
        >
          <Reply className="h-2.5 w-2.5" />
          Reply
        </button>
      )}
      {showReply && onReply && (
        <InlineReplyForm
          onSubmit={(body) => onReply(lastId, body)}
          onCancel={() => setShowReply(false)}
        />
      )}
    </div>
  );
}

function CommentBubble({
  comment,
  currentUser,
  onEdit,
  onDelete,
  isReply = false,
}: {
  comment: InlineComment;
  currentUser?: string;
  onEdit?: (commentId: number | string, body: string) => Promise<void>;
  onDelete?: (commentId: number | string) => Promise<void>;
  isReply?: boolean;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(comment.body);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const editRef = useRef<HTMLTextAreaElement>(null);
  const isOwn = currentUser && comment.user?.login === currentUser;

  useEffect(() => {
    if (editing) editRef.current?.focus();
  }, [editing]);

  const handleDelete = async () => {
    if (!onDelete) return;
    setDeleting(true);
    try {
      await onDelete(comment.id);
    } finally {
      setDeleting(false);
      setMenuOpen(false);
    }
  };

  const handleStartEdit = () => {
    setEditText(comment.body);
    setEditError(null);
    setEditing(true);
    setMenuOpen(false);
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setEditText(comment.body);
    setEditError(null);
  };

  const handleSaveEdit = async () => {
    if (!onEdit || !editText.trim() || editText.trim() === comment.body) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setEditError(null);
    try {
      await onEdit(comment.id, editText.trim());
      setEditing(false);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : "Failed to update comment");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="group/comment">
      <div className="flex items-center gap-1.5 text-[10px] text-[var(--o-text-tertiary)]">
        {isReply ? (
          <Reply className="h-2.5 w-2.5" />
        ) : (
          <MessageSquare className="h-3 w-3" />
        )}
        <span className="font-medium text-[var(--o-text-secondary)]">
          {comment.user?.login ?? "unknown"}
        </span>
        {comment.isPending && (
          <span className="rounded-full bg-amber-100 px-1.5 py-px text-[9px] font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
            Pending
          </span>
        )}
        <span className="flex-1" />
        {isOwn && (onDelete || onEdit) && !editing && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen(!menuOpen)}
              className="rounded p-0.5 opacity-0 transition-opacity group-hover/comment:opacity-100 hover:bg-[var(--o-bg-subtle)]"
            >
              <MoreHorizontal className="h-3 w-3" />
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 top-full z-20 mt-0.5 w-28 rounded-md border border-[var(--o-border)] bg-[var(--o-bg-raised)] py-0.5 shadow-lg">
                  {onEdit && (
                    <button
                      type="button"
                      onClick={handleStartEdit}
                      className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-[11px] text-[var(--o-text)] hover:bg-[var(--o-bg-subtle)]"
                    >
                      <Pencil className="h-3 w-3" />
                      Edit
                    </button>
                  )}
                  {onDelete && (
                    <button
                      type="button"
                      onClick={() => void handleDelete()}
                      disabled={deleting}
                      className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-[11px] text-[var(--o-danger)] hover:bg-[var(--o-bg-subtle)] disabled:opacity-50"
                    >
                      <Trash2 className="h-3 w-3" />
                      {deleting ? "Deleting..." : "Delete"}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </div>
      {editing ? (
        <div className="mt-1">
          <textarea
            ref={editRef}
            value={editText}
            onChange={(e) => { setEditText(e.target.value); setEditError(null); }}
            onKeyDown={(e) => {
              if (e.key === "Escape") handleCancelEdit();
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void handleSaveEdit();
            }}
            rows={3}
            className="w-full resize-y rounded border border-[var(--o-border)] bg-[var(--o-bg)] px-2 py-1 font-sans text-[11px] text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none"
          />
          {editError && (
            <div className="mt-1 flex items-start gap-1 rounded bg-[var(--o-pastel-rose)] px-2 py-1 text-[10px] text-[var(--o-pastel-rose-fg)]">
              <AlertTriangle className="mt-0.5 h-2.5 w-2.5 shrink-0" />
              <span>{editError}</span>
            </div>
          )}
          <div className="mt-1 flex justify-end gap-1">
            <button
              type="button"
              onClick={handleCancelEdit}
              disabled={saving}
              className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
            >
              <X className="h-2.5 w-2.5" />
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSaveEdit()}
              disabled={saving || !editText.trim()}
              className="inline-flex items-center gap-1 rounded bg-[var(--o-accent)] px-2 py-0.5 text-[10px] font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <Check className="h-2.5 w-2.5" />}
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-0.5 font-sans text-[var(--o-text-secondary)]">
          <MarkdownView
            content={prepareCommentMarkdown(comment.body)}
            variant="chat"
            breaks
            className="space-y-1 break-words text-[11px] leading-snug text-[var(--o-text-secondary)] [&_pre]:whitespace-pre-wrap [&_pre]:break-words"
          />
        </div>
      )}
    </div>
  );
}

function InlineReplyForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (body: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(text.trim());
      setText("");
      onCancel();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to post reply");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-1.5 border-t border-[var(--o-border)] pt-1.5">
      <textarea
        autoFocus
        value={text}
        onChange={(e) => { setText(e.target.value); setError(null); }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void handleSubmit();
        }}
        placeholder="Reply... (Ctrl+Enter to submit)"
        rows={2}
        className="w-full resize-y rounded border border-[var(--o-border)] bg-[var(--o-bg)] px-2 py-1 font-sans text-[11px] text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none"
      />
      {error && (
        <div className="mt-1 flex items-start gap-1 rounded bg-[var(--o-pastel-rose)] px-2 py-1 text-[10px] text-[var(--o-pastel-rose-fg)]">
          <AlertTriangle className="mt-0.5 h-2.5 w-2.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      <div className="mt-1 flex justify-end gap-1">
        <button type="button" onClick={onCancel} disabled={submitting} className="rounded px-2 py-0.5 text-[10px] text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]">Cancel</button>
        <button type="button" onClick={() => void handleSubmit()} disabled={!text.trim() || submitting} className="inline-flex items-center gap-1 rounded bg-[var(--o-accent)] px-2 py-0.5 text-[10px] font-medium text-white hover:opacity-90 disabled:opacity-50">
          {submitting && <Loader2 className="h-2.5 w-2.5 animate-spin" />}
          Reply
        </button>
      </div>
    </div>
  );
}

export default function DiffViewer({
  files,
  rawDiff,
  existingComments = [],
  currentUser,
  hasPendingReview = false,
  projectId,
  prNumber,
  owner,
  repo,
  provider = "github",
  onAddComment,
  onStartReview,
  onAddReviewComment,
  onReplyComment,
  onEditComment,
  onDeleteComment,
}: DiffViewerProps) {
  const [selectedFile, setSelectedFile] = useState<string | null>(
    files.length > 0 ? files[0].filename : null,
  );

  const [anchor, setAnchor] = useState<LineAnchor | null>(null);
  const [end, setEnd] = useState<LineAnchor | null>(null);
  /** Per-file gap reveals: gap index → { top, bottom }. */
  const [gapRevealsByFile, setGapRevealsByFile] = useState<Record<string, Record<number, GapReveal>>>({});
  const [fileContentCache, setFileContentCache] = useState<Record<string, string[]>>({});
  const fileContentCacheRef = useRef(fileContentCache);
  fileContentCacheRef.current = fileContentCache;
  const [expandLoading, setExpandLoading] = useState(false);
  const [expandError, setExpandError] = useState<string | null>(null);
  const [flowOpen, setFlowOpen] = useState(false);
  const [flowExpanded, setFlowExpanded] = useState(false);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [flowMermaid, setFlowMermaid] = useState<string>("");
  const [flowLabel, setFlowLabel] = useState<string>("");
  const [flowRange, setFlowRange] = useState<string>("");

  const canComment = Boolean(onAddComment || onStartReview);
  const canExpand = Boolean(projectId && prNumber != null && owner && repo);
  const canFlow = canExpand;
  const activeFile = files.find((f) => f.filename === selectedFile);
  const hunks = useMemo(
    () => (activeFile?.patch ? parsePatch(activeFile.patch) : []),
    [activeFile?.patch],
  );
  const fileLines = selectedFile ? fileContentCache[selectedFile] : undefined;
  const fileLen = fileLines?.length ?? null;
  const gaps = useMemo(() => computeGaps(hunks, fileLen), [hunks, fileLen]);
  const gapReveals = (selectedFile && gapRevealsByFile[selectedFile]) || {};

  const ensureFileContent = useCallback(
    async (filename: string): Promise<string[] | null> => {
      const cached = fileContentCacheRef.current[filename];
      if (cached) return cached;
      if (!projectId || prNumber == null || !owner || !repo) return null;
      setExpandLoading(true);
      setExpandError(null);
      try {
        const res = await getPullFileContent(
          projectId,
          prNumber,
          filename,
          owner,
          repo,
          provider,
        );
        const lines = (res.content ?? "").split("\n");
        // split keeps a trailing empty from final newline; match editor line count.
        if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
        setFileContentCache((prev) => ({ ...prev, [filename]: lines }));
        return lines;
      } catch (err) {
        setExpandError(err instanceof Error ? err.message : "Could not load file content.");
        return null;
      } finally {
        setExpandLoading(false);
      }
    },
    [projectId, prNumber, owner, repo, provider],
  );

  const bumpGapReveal = useCallback(
    (
      filename: string,
      gapIndex: number,
      edge: "top" | "bottom" | "all",
      gapSize: number,
    ) => {
      setGapRevealsByFile((prev) => {
        const fileMap = { ...(prev[filename] || {}) };
        const cur = fileMap[gapIndex] || { top: 0, bottom: 0 };
        if (edge === "all") {
          fileMap[gapIndex] = { top: gapSize, bottom: 0 };
        } else if (edge === "top") {
          fileMap[gapIndex] = { ...cur, top: Math.min(gapSize, cur.top + EXPAND_STEP) };
        } else {
          fileMap[gapIndex] = { ...cur, bottom: Math.min(gapSize, cur.bottom + EXPAND_STEP) };
        }
        return { ...prev, [filename]: fileMap };
      });
    },
    [],
  );

  const handleGapExpand = useCallback(
    async (gapIndex: number, edge: "top" | "bottom" | "all") => {
      if (!selectedFile || !canExpand) return;
      const lines = await ensureFileContent(selectedFile);
      if (!lines) return;
      const nextGaps = computeGaps(
        activeFile?.patch ? parsePatch(activeFile.patch) : hunks,
        lines.length,
      );
      const gap = nextGaps[gapIndex];
      if (!gap) return;
      const size = gap.end - gap.start + 1;
      bumpGapReveal(selectedFile, gapIndex, edge, size);
    },
    [selectedFile, canExpand, ensureFileContent, activeFile?.patch, hunks, bumpGapReveal],
  );

  const handleShowFlow = useCallback(async () => {
    if (!selectedFile || !canFlow || !projectId || prNumber == null || !owner || !repo) return;
    setFlowOpen(true);
    setFlowLoading(true);
    setFlowError(null);
    setFlowMermaid("");
    setFlowLabel("");
    setFlowRange("");
    try {
      const firstNew = hunks
        .flatMap((h) => h.lines.map((l) => l.newLine))
        .find((n): n is number => typeof n === "number");
      const res = await getPullFlowChart(projectId, prNumber, owner, repo, provider, {
        path: selectedFile,
        start_line: firstNew,
        patch: activeFile?.patch,
      });
      if (res.error && !res.mermaid) {
        setFlowError(res.error);
        return;
      }
      setFlowMermaid(res.mermaid || "");
      setFlowLabel(res.label || selectedFile);
      setFlowRange(
        res.start_line && res.end_line ? `L${res.start_line}–${res.end_line}` : "",
      );
      if (!res.mermaid) setFlowError(res.error || "No flowchart returned.");
    } catch (err) {
      setFlowError(err instanceof Error ? err.message : "Could not build flowchart.");
    } finally {
      setFlowLoading(false);
    }
  }, [
    selectedFile,
    canFlow,
    projectId,
    prNumber,
    owner,
    repo,
    provider,
    hunks,
    activeFile?.patch,
  ]);

  const allThreads = useMemo(() => groupThreads(existingComments), [existingComments]);

  const threadsByLine = useMemo(() => {
    const result = new Map<string, CommentThread[]>();
    if (!selectedFile) return result;
    for (const thread of allThreads) {
      if (thread.root.path !== selectedFile || thread.root.line == null) continue;
      const side = (thread.root.side ?? "RIGHT").toUpperCase();
      const key = `${thread.root.line}:${side}`;
      const bucket = result.get(key) ?? [];
      bucket.push(thread);
      result.set(key, bucket);
    }
    return result;
  }, [allThreads, selectedFile]);

  const fileThreads = useMemo(
    () => allThreads.filter((thread) => thread.root.path === selectedFile && thread.root.line == null),
    [allThreads, selectedFile],
  );

  const commentCountByFile = useMemo(() => {
    const counts = new Map<string, number>();
    for (const thread of allThreads) {
      if (!thread.root.path) continue;
      counts.set(thread.root.path, (counts.get(thread.root.path) ?? 0) + 1);
    }
    return counts;
  }, [allThreads]);

  const clearSelection = useCallback(() => {
    setAnchor(null);
    setEnd(null);
  }, []);

  useEffect(() => {
    clearSelection();
    setExpandError(null);
    setFlowOpen(false);
    setFlowExpanded(false);
    setFlowError(null);
    setFlowMermaid("");
    setFlowLabel("");
    setFlowRange("");
  }, [selectedFile, clearSelection]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") clearSelection(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [clearSelection]);

  const rangeStart = anchor && end
    ? (anchor.globalIdx <= end.globalIdx ? anchor : end) : anchor;
  const rangeEnd = anchor && end
    ? (anchor.globalIdx <= end.globalIdx ? end : anchor) : anchor;
  const showFormAfterIdx = rangeEnd?.globalIdx ?? null;

  const handlePlusClick = useCallback(
    (lineAnchor: LineAnchor, shiftKey: boolean) => {
      if (!anchor) {
        setAnchor(lineAnchor);
        setEnd(null);
      } else if (shiftKey) {
        setEnd(lineAnchor);
      } else {
        setAnchor(lineAnchor);
        setEnd(null);
      }
    },
    [anchor],
  );

  const buildParams = useCallback(
    (body: string): AddCommentParams | null => {
      if (!selectedFile || !rangeStart) return null;
      const params: AddCommentParams = {
        path: selectedFile,
        line: rangeEnd!.lineNo,
        side: rangeEnd!.side,
        body,
      };
      if (end && rangeStart.globalIdx !== rangeEnd!.globalIdx) {
        params.startLine = rangeStart.lineNo;
        params.startSide = rangeStart.side;
      }
      return params;
    },
    [selectedFile, rangeStart, rangeEnd, end],
  );

  const handleSingleComment = useCallback(
    async (body: string) => {
      const params = buildParams(body);
      if (!params || !onAddComment) return;
      await onAddComment(params);
      clearSelection();
    },
    [buildParams, onAddComment, clearSelection],
  );

  const handleStartReview = useCallback(
    async (body: string) => {
      const params = buildParams(body);
      if (!params || !onStartReview) return;
      await onStartReview(params);
      clearSelection();
    },
    [buildParams, onStartReview, clearSelection],
  );

  const handleAddReviewComment = useCallback(
    async (body: string) => {
      const params = buildParams(body);
      if (!params || !onAddReviewComment) return;
      await onAddReviewComment(params);
      clearSelection();
    },
    [buildParams, onAddReviewComment, clearSelection],
  );

  if (files.length === 0 && !rawDiff) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-[var(--o-text-secondary)]">
        No file changes found.
      </div>
    );
  }

  let globalLineIdx = 0;

  return (
    <div className="relative flex h-full min-h-0 flex-1">
      {/* File tree */}
      <div className="w-56 shrink-0 overflow-y-auto border-r border-[var(--o-border)] bg-[var(--o-bg-raised)]">
        <div className="px-2 py-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
          Files ({files.length})
        </div>
        <div className="space-y-0.5 px-1 pb-2">
          {files.map((f) => (
            <button
              key={f.filename}
              type="button"
              onClick={() => setSelectedFile(f.filename)}
              className={clsx(
                "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors",
                selectedFile === f.filename
                  ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                  : "text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]",
              )}
            >
              <FileStatusBadge status={f.status} />
              <span className="min-w-0 truncate">{f.filename.split("/").pop()}</span>
              {(commentCountByFile.get(f.filename) ?? 0) > 0 && (
                <span className="inline-flex shrink-0 items-center gap-0.5 rounded bg-[var(--o-accent-muted)] px-1 text-[10px] text-[var(--o-accent)]">
                  <MessageSquare className="h-2.5 w-2.5" />
                  {commentCountByFile.get(f.filename)}
                </span>
              )}
              <span className="ml-auto shrink-0 text-[10px] text-[var(--o-text-tertiary)]">
                <span className="text-[var(--o-pastel-mint-fg)]">+{f.additions}</span>
                {" "}
                <span className="text-[var(--o-pastel-rose-fg)]">-{f.deletions}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Diff content + optional flow panel */}
      <div className="flex min-w-0 flex-1 overflow-hidden bg-[var(--o-bg)]">
      <div className="min-w-0 flex-1 overflow-auto">
        {activeFile && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-4 py-2">
            <span className="text-xs font-medium text-[var(--o-text)]">{activeFile.filename}</span>
            <span className="text-[11px] text-[var(--o-text-tertiary)]">
              <span className="text-[var(--o-pastel-mint-fg)]">+{activeFile.additions}</span>
              {" "}
              <span className="text-[var(--o-pastel-rose-fg)]">-{activeFile.deletions}</span>
            </span>
            {canFlow && hunks.length > 0 && activeFile.status !== "removed" && (
              <button
                type="button"
                disabled={flowLoading}
                onClick={() => void handleShowFlow()}
                className={clsx(
                  "ml-auto inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium transition-colors disabled:opacity-50",
                  flowOpen
                    ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                    : "text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]",
                )}
              >
                {flowLoading ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <GitBranch className="h-3 w-3" />
                )}
                Show flow
              </button>
            )}
            {expandError && (
              <div className="w-full text-[10px] text-[var(--o-danger)]">{expandError}</div>
            )}
          </div>
        )}

        {canComment && hunks.length > 0 && (
          <div className="flex items-center gap-2 border-b border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-4 py-1.5 text-[11px] text-[var(--o-text-tertiary)]">
            <Info className="h-3 w-3 shrink-0" />
            {!anchor ? (
              <span>
                Click <Plus className="inline h-3 w-3 rounded border border-current align-text-bottom" /> on a line to comment.
                {" "}Hold{" "}
                <kbd className="rounded bg-[var(--o-bg-raised)] px-1 py-0.5 text-[10px] font-medium">Shift</kbd>
                {" "}and click <Plus className="inline h-3 w-3 rounded border border-current align-text-bottom" /> on another line for a multi-line comment.
              </span>
            ) : !end ? (
              <span>
                Line {rangeStart?.lineNo} selected.
                {" "}Hold{" "}
                <kbd className="rounded bg-[var(--o-bg-raised)] px-1 py-0.5 text-[10px] font-medium">Shift</kbd>
                {" "}and click the end line, or write below.
                {" "}<kbd className="rounded bg-[var(--o-bg-raised)] px-1 py-0.5 text-[10px] font-medium">Esc</kbd> to cancel.
              </span>
            ) : (
              <span>
                Lines {rangeStart?.lineNo}–{rangeEnd?.lineNo} selected.
                {" "}<kbd className="rounded bg-[var(--o-bg-raised)] px-1 py-0.5 text-[10px] font-medium">Esc</kbd> to cancel.
              </span>
            )}
          </div>
        )}

        {hunks.length > 0 ? (
          <div className="min-w-0 font-mono text-[12px] leading-5">
            {hunks.map((hunk, hi) => {
              const gap = gaps[hi];
              const reveal = gap ? clampGapReveal(gap, gapReveals[gap.index]) : null;
              const topLines =
                gap && fileLines && reveal && reveal.top > 0
                  ? contextLinesFromFile(fileLines, gap.start, gap.start + reveal.top - 1)
                  : [];
              const bottomLines =
                gap && fileLines && reveal && reveal.bottom > 0
                  ? contextLinesFromFile(fileLines, gap.end - reveal.bottom + 1, gap.end)
                  : [];
              const gapRemaining = reveal?.remaining ?? (gap ? gap.end - gap.start + 1 : 0);
              const showGapExpander =
                canExpand &&
                activeFile?.status !== "removed" &&
                gap != null &&
                gapRemaining > 0;
              // Gaps above a hunk grow upward toward that hunk (GitHub: one unfold, not ↑+↓).
              const gapEdge: "top" | "bottom" = "bottom";

              const renderLines = (lines: DiffLine[], keyPrefix: string, attachFileThreads: boolean) =>
                lines.map((line, li) => {
                  const currentIdx = globalLineIdx++;
                  const lineNo = lineNumber(line);
                  const side = lineSide(line.type);
                  const key = `${lineNo}:${side}`;
                  let lineThreads = threadsByLine.get(key) ?? [];
                  if (line.type === "context" && line.oldLine != null) {
                    const leftThreads = threadsByLine.get(`${line.oldLine}:LEFT`) ?? [];
                    if (leftThreads.length) lineThreads = [...lineThreads, ...leftThreads];
                  }
                  if (attachFileThreads && li === 0 && fileThreads.length) {
                    lineThreads = [...fileThreads, ...lineThreads];
                  }

                  const inRange =
                    rangeStart && rangeEnd
                      ? currentIdx >= rangeStart.globalIdx && currentIdx <= rangeEnd.globalIdx
                      : false;
                  const isAnchorLine = anchor?.globalIdx === currentIdx;
                  const showForm = showFormAfterIdx === currentIdx && anchor !== null;

                  return (
                    <React.Fragment key={`${keyPrefix}-${li}`}>
                      <tr className="group">
                        {canComment && (
                          <td
                            className={clsx(
                              "w-[1%] select-none whitespace-nowrap align-top",
                              inRange && "bg-[rgba(96,165,250,0.10)]",
                              line.type === "add" && !inRange && "bg-[rgba(74,222,128,0.12)]",
                              line.type === "remove" && !inRange && "bg-[rgba(248,113,113,0.12)]",
                            )}
                          >
                            <button
                              type="button"
                              onClick={(e) =>
                                handlePlusClick(
                                  { lineNo, side, type: line.type, globalIdx: currentIdx },
                                  e.shiftKey,
                                )
                              }
                              className={clsx(
                                "flex h-5 w-5 items-center justify-center rounded text-[var(--o-accent)] transition-opacity",
                                isAnchorLine
                                  ? "opacity-100 bg-[var(--o-accent-muted)]"
                                  : "opacity-0 group-hover:opacity-100 hover:bg-[var(--o-accent-muted)]",
                              )}
                              title={anchor ? "Hold Shift and click to select range end" : "Add comment"}
                            >
                              <Plus className="h-3 w-3" />
                            </button>
                          </td>
                        )}
                        <td
                          className={clsx(
                            "w-[1%] select-none whitespace-nowrap px-1.5 text-right align-top text-[var(--o-text-tertiary)]",
                            inRange && "bg-[rgba(96,165,250,0.10)]",
                            line.type === "add" && !inRange && "bg-[rgba(74,222,128,0.12)]",
                            line.type === "remove" && !inRange && "bg-[rgba(248,113,113,0.12)]",
                          )}
                        >
                          {line.oldLine ?? ""}
                        </td>
                        <td
                          className={clsx(
                            "w-[1%] select-none whitespace-nowrap px-1.5 text-right align-top text-[var(--o-text-tertiary)]",
                            inRange && "bg-[rgba(96,165,250,0.10)]",
                            line.type === "add" && !inRange && "bg-[rgba(74,222,128,0.12)]",
                            line.type === "remove" && !inRange && "bg-[rgba(248,113,113,0.12)]",
                          )}
                        >
                          {line.newLine ?? ""}
                        </td>
                        <td
                          className={clsx(
                            "w-[1%] select-none whitespace-nowrap text-center align-top",
                            inRange && "bg-[rgba(96,165,250,0.08)]",
                            line.type === "add" && !inRange && "bg-[rgba(74,222,128,0.08)]",
                            line.type === "remove" && !inRange && "bg-[rgba(248,113,113,0.08)]",
                          )}
                        >
                          {line.type === "add" ? (
                            <span className="text-[var(--o-pastel-mint-fg)]">+</span>
                          ) : line.type === "remove" ? (
                            <span className="text-[var(--o-pastel-rose-fg)]">-</span>
                          ) : (
                            "\u00a0"
                          )}
                        </td>
                        <td
                          className={clsx(
                            "whitespace-pre-wrap break-all pr-4 align-top",
                            inRange && "bg-[rgba(96,165,250,0.06)]",
                            line.type === "add" && !inRange && "bg-[rgba(74,222,128,0.08)] text-[var(--o-pastel-mint-fg)]",
                            line.type === "remove" && !inRange && "bg-[rgba(248,113,113,0.08)] text-[var(--o-pastel-rose-fg)]",
                            line.type === "context" && !inRange && !line.expanded && "text-[var(--o-text-secondary)]",
                            line.expanded && !inRange && "bg-[var(--o-bg-subtle)]/40 text-[var(--o-text-tertiary)]",
                            inRange && "text-[var(--o-text)]",
                          )}
                        >
                          {line.content}
                        </td>
                      </tr>
                      {lineThreads.length > 0 && (
                        <tr>
                          <td colSpan={canComment ? 5 : 4} className="border-b border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-1 font-sans">
                            {lineThreads.map((thread) => (
                              <InlineThread
                                key={thread.root.id}
                                thread={thread}
                                currentUser={currentUser}
                                onReply={onReplyComment}
                                onEdit={onEditComment}
                                onDelete={onDeleteComment}
                              />
                            ))}
                          </td>
                        </tr>
                      )}
                      {showForm && (
                        <tr>
                          <td colSpan={canComment ? 5 : 4} className="px-2 py-1">
                            <CommentForm
                              hasPendingReview={hasPendingReview}
                              onSingleComment={onAddComment ? handleSingleComment : undefined}
                              onStartReview={onStartReview ? handleStartReview : undefined}
                              onAddReviewComment={onAddReviewComment ? handleAddReviewComment : undefined}
                              onCancel={clearSelection}
                            />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                });

              return (
                <div key={hi}>
                  {topLines.length > 0 && (
                    <table className="w-full border-collapse">
                      <tbody>{renderLines(topLines, `g${hi}-top`, false)}</tbody>
                    </table>
                  )}
                  {showGapExpander && gap && (
                    <GapExpander
                      remaining={gapRemaining}
                      loading={expandLoading}
                      edge={gapEdge}
                      onExpand={(edge) => void handleGapExpand(gap.index, edge)}
                    />
                  )}
                  {bottomLines.length > 0 && (
                    <table className="w-full border-collapse">
                      <tbody>{renderLines(bottomLines, `g${hi}-bot`, false)}</tbody>
                    </table>
                  )}
                  <div className="bg-[var(--o-pastel-sky)] px-4 py-0.5 text-[11px] text-[var(--o-pastel-sky-fg)]">
                    {hunk.header}
                  </div>
                  <table className="w-full border-collapse">
                    <tbody>
                      {renderLines(hunk.lines, `h${hi}`, hi === 0)}
                    </tbody>
                  </table>
                </div>
              );
            })}
            {(() => {
              const trail = gaps[hunks.length];
              const reveal = trail ? clampGapReveal(trail, gapReveals[trail.index]) : null;
              const topLines =
                trail && fileLines && reveal && reveal.top > 0
                  ? contextLinesFromFile(fileLines, trail.start, trail.start + reveal.top - 1)
                  : [];
              const bottomLines =
                trail && fileLines && reveal && reveal.bottom > 0
                  ? contextLinesFromFile(fileLines, trail.end - reveal.bottom + 1, trail.end)
                  : [];
              const remaining = reveal?.remaining ?? null;
              const showTrailExpander =
                canExpand &&
                activeFile?.status !== "removed" &&
                (trail != null
                  ? (remaining ?? trail.end - trail.start + 1) > 0
                  : fileLen == null);
              const renderTrailLines = (lines: DiffLine[], keyPrefix: string) =>
                lines.map((line, li) => {
                  const currentIdx = globalLineIdx++;
                  const lineNo = lineNumber(line);
                  const side = lineSide(line.type);
                  const key = `${lineNo}:${side}`;
                  const lineThreads = threadsByLine.get(key) ?? [];
                  const inRange =
                    rangeStart && rangeEnd
                      ? currentIdx >= rangeStart.globalIdx && currentIdx <= rangeEnd.globalIdx
                      : false;
                  const isAnchorLine = anchor?.globalIdx === currentIdx;
                  const showForm = showFormAfterIdx === currentIdx && anchor !== null;
                  return (
                    <React.Fragment key={`${keyPrefix}-${li}`}>
                      <tr className="group">
                        {canComment && (
                          <td className={clsx("w-[1%] select-none whitespace-nowrap align-top", inRange && "bg-[rgba(96,165,250,0.10)]")}>
                            <button
                              type="button"
                              onClick={(e) =>
                                handlePlusClick(
                                  { lineNo, side, type: line.type, globalIdx: currentIdx },
                                  e.shiftKey,
                                )
                              }
                              className={clsx(
                                "flex h-5 w-5 items-center justify-center rounded text-[var(--o-accent)] transition-opacity",
                                isAnchorLine
                                  ? "opacity-100 bg-[var(--o-accent-muted)]"
                                  : "opacity-0 group-hover:opacity-100 hover:bg-[var(--o-accent-muted)]",
                              )}
                              title={anchor ? "Hold Shift and click to select range end" : "Add comment"}
                            >
                              <Plus className="h-3 w-3" />
                            </button>
                          </td>
                        )}
                        <td className="w-[1%] select-none whitespace-nowrap px-1.5 text-right align-top text-[var(--o-text-tertiary)]">{line.oldLine ?? ""}</td>
                        <td className="w-[1%] select-none whitespace-nowrap px-1.5 text-right align-top text-[var(--o-text-tertiary)]">{line.newLine ?? ""}</td>
                        <td className="w-[1%] select-none whitespace-nowrap text-center align-top">{"\u00a0"}</td>
                        <td
                          className={clsx(
                            "whitespace-pre-wrap break-all pr-4 align-top",
                            line.expanded && "bg-[var(--o-bg-subtle)]/40 text-[var(--o-text-tertiary)]",
                            !line.expanded && "text-[var(--o-text-secondary)]",
                          )}
                        >
                          {line.content}
                        </td>
                      </tr>
                      {lineThreads.length > 0 && (
                        <tr>
                          <td colSpan={canComment ? 5 : 4} className="border-b border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-1 font-sans">
                            {lineThreads.map((thread) => (
                              <InlineThread
                                key={thread.root.id}
                                thread={thread}
                                currentUser={currentUser}
                                onReply={onReplyComment}
                                onEdit={onEditComment}
                                onDelete={onDeleteComment}
                              />
                            ))}
                          </td>
                        </tr>
                      )}
                      {showForm && (
                        <tr>
                          <td colSpan={canComment ? 5 : 4} className="px-2 py-1">
                            <CommentForm
                              hasPendingReview={hasPendingReview}
                              onSingleComment={onAddComment ? handleSingleComment : undefined}
                              onStartReview={onStartReview ? handleStartReview : undefined}
                              onAddReviewComment={onAddReviewComment ? handleAddReviewComment : undefined}
                              onCancel={clearSelection}
                            />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                });
              if (!showTrailExpander && topLines.length === 0 && bottomLines.length === 0) return null;
              return (
                <div key="trail">
                  {topLines.length > 0 && (
                    <table className="w-full border-collapse">
                      <tbody>{renderTrailLines(topLines, "trail-top")}</tbody>
                    </table>
                  )}
                  {showTrailExpander && (
                    <GapExpander
                      remaining={trail ? (remaining ?? trail.end - trail.start + 1) : null}
                      loading={expandLoading}
                      edge="top"
                      onExpand={(edge) => void handleGapExpand(hunks.length, edge === "all" ? "all" : "top")}
                    />
                  )}
                  {bottomLines.length > 0 && (
                    <table className="w-full border-collapse">
                      <tbody>{renderTrailLines(bottomLines, "trail-bot")}</tbody>
                    </table>
                  )}
                </div>
              );
            })()}
          </div>
        ) : rawDiff ? (
          <pre className="whitespace-pre-wrap p-4 font-mono text-xs text-[var(--o-text-secondary)]">
            {rawDiff}
          </pre>
        ) : (
          <div className="flex items-center justify-center py-12 text-sm text-[var(--o-text-secondary)]">
            {activeFile ? "No patch data available for this file." : "Select a file to view changes."}
          </div>
        )}
      </div>

      {flowOpen && !flowExpanded && (
        <aside className="flex w-[min(100%,36rem)] shrink-0 flex-col border-l border-[var(--o-border)] bg-[var(--o-bg-raised)]">
          <div className="flex items-start gap-2 border-b border-[var(--o-border)] px-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="text-[11px] font-semibold text-[var(--o-text)]">Flow</div>
              {(flowLabel || flowRange) && (
                <div className="truncate text-[10px] text-[var(--o-text-tertiary)]" title={flowLabel}>
                  {flowRange ? `${flowRange} · ` : ""}
                  {flowLabel}
                </div>
              )}
            </div>
            {flowMermaid && !flowLoading && !flowError && (
              <button
                type="button"
                onClick={() => setFlowExpanded(true)}
                className="rounded p-1 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
                title="Expand flowchart"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                setFlowOpen(false);
                setFlowExpanded(false);
              }}
              className="rounded p-1 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
              title="Close"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-3">
            {flowLoading && (
              <div className="flex items-center gap-2 text-[11px] text-[var(--o-text-tertiary)]">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Building flowchart…
              </div>
            )}
            {!flowLoading && flowError && (
              <div className="text-[11px] text-[var(--o-danger)]">{flowError}</div>
            )}
            {!flowLoading && !flowError && flowMermaid && (
              <MermaidBlock chart={flowMermaid} density="review" scrollable />
            )}
          </div>
        </aside>
      )}
      </div>

      {flowOpen && flowExpanded && (
        <div className="absolute inset-0 z-20 flex flex-col bg-[var(--o-bg)]/95 backdrop-blur-sm">
          <div className="flex items-start gap-2 border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-4 py-2">
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold text-[var(--o-text)]">Flow</div>
              {(flowLabel || flowRange) && (
                <div className="truncate text-[11px] text-[var(--o-text-tertiary)]" title={flowLabel}>
                  {flowRange ? `${flowRange} · ` : ""}
                  {flowLabel}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => setFlowExpanded(false)}
              className="rounded p-1.5 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
              title="Back to side panel"
            >
              <Minimize2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => {
                setFlowOpen(false);
                setFlowExpanded(false);
              }}
              className="rounded p-1.5 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
              title="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-6">
            {flowMermaid && <MermaidBlock chart={flowMermaid} density="review" scrollable />}
          </div>
        </div>
      )}
    </div>
  );
}

export type { DiffFile };
