import clsx from "clsx";
import { AlertTriangle, Info, Loader2, MessageSquare, Plus, Reply } from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface DiffFile {
  filename: string;
  status: string;
  additions: number;
  deletions: number;
  patch?: string;
}

interface InlineComment {
  id: number | string;
  path: string;
  line?: number;
  side?: string;
  body: string;
  user?: { login: string };
  created_at?: string;
  in_reply_to_id?: number;
}

interface LineAnchor {
  lineNo: number;
  side: "LEFT" | "RIGHT";
  type: "add" | "remove" | "context";
  /** Global index across all hunks for range comparison */
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
  onAddComment?: (params: AddCommentParams) => Promise<void>;
  onReplyComment?: (commentId: number, body: string) => Promise<void>;
}

function parsePatch(patch: string): Array<{
  header: string;
  lines: Array<{
    type: "add" | "remove" | "context";
    content: string;
    oldLine?: number;
    newLine?: number;
  }>;
}> {
  const hunks: ReturnType<typeof parsePatch> = [];
  const hunkParts = patch.split(/^(@@[^@]+@@.*$)/m).filter(Boolean);

  for (let i = 0; i < hunkParts.length; i++) {
    const part = hunkParts[i];
    if (!part.startsWith("@@")) continue;

    const header = part;
    const body = hunkParts[i + 1] ?? "";
    const match = header.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    let oldLine = match ? parseInt(match[1], 10) : 1;
    let newLine = match ? parseInt(match[2], 10) : 1;

    const lines: (typeof hunks)[0]["lines"] = [];
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

function lineSide(type: "add" | "remove" | "context"): "LEFT" | "RIGHT" {
  return type === "remove" ? "LEFT" : "RIGHT";
}

function lineNumber(line: { type: string; oldLine?: number; newLine?: number }): number {
  return line.type === "remove" ? (line.oldLine ?? 0) : (line.newLine ?? 0);
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

function CommentForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (body: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleSubmit = async () => {
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(text.trim());
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : typeof err === "object" && err !== null && "response" in err
            ? String(
                (
                  (err as { response?: { data?: { detail?: string } } }).response?.data
                    ?.detail
                ) ?? "Failed to post comment",
              )
            : "Failed to post comment";
      setError(msg);
    } finally {
      setSubmitting(false);
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
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void handleSubmit();
        }}
        placeholder="Write a comment... (Ctrl+Enter to submit)"
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
          disabled={submitting}
          className="rounded-md px-3 py-1.5 text-xs text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={!text.trim() || submitting}
          className="inline-flex items-center gap-1.5 rounded-md bg-[var(--o-accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {submitting && <Loader2 className="h-3 w-3 animate-spin" />}
          Comment
        </button>
      </div>
    </div>
  );
}

function InlineThread({
  thread,
  onReply,
}: {
  thread: { root: InlineComment; replies: InlineComment[] };
  onReply?: (commentId: number, body: string) => Promise<void>;
}) {
  const [showReply, setShowReply] = useState(false);
  const { root, replies } = thread;
  const lastId = replies.length > 0 ? Number(replies[replies.length - 1].id) : Number(root.id);

  return (
    <div className="my-1 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] px-3 py-2">
      <div className="flex items-center gap-1.5 text-[10px] text-[var(--o-text-tertiary)]">
        <MessageSquare className="h-3 w-3" />
        <span className="font-medium text-[var(--o-text-secondary)]">
          {root.user?.login ?? "unknown"}
        </span>
      </div>
      <p className="mt-0.5 whitespace-normal font-sans text-[11px] text-[var(--o-text-secondary)]">
        {root.body}
      </p>

      {replies.map((r) => (
        <div key={r.id} className="mt-1.5 border-l-2 border-[var(--o-border)] pl-2.5">
          <div className="flex items-center gap-1.5 text-[10px] text-[var(--o-text-tertiary)]">
            <Reply className="h-2.5 w-2.5" />
            <span className="font-medium text-[var(--o-text-secondary)]">
              {r.user?.login ?? "unknown"}
            </span>
          </div>
          <p className="mt-0.5 whitespace-normal font-sans text-[11px] text-[var(--o-text-secondary)]">
            {r.body}
          </p>
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
  onAddComment,
  onReplyComment,
}: DiffViewerProps) {
  const [selectedFile, setSelectedFile] = useState<string | null>(
    files.length > 0 ? files[0].filename : null,
  );

  const [anchor, setAnchor] = useState<LineAnchor | null>(null);
  const [end, setEnd] = useState<LineAnchor | null>(null);

  const activeFile = files.find((f) => f.filename === selectedFile);
  const hunks = useMemo(
    () => (activeFile?.patch ? parsePatch(activeFile.patch) : []),
    [activeFile?.patch],
  );

  const threadsByLine = useMemo(() => {
    if (!selectedFile) return new Map<string, { root: InlineComment; replies: InlineComment[] }[]>();
    const fileComments = existingComments.filter((c) => c.path === selectedFile);

    const threads: { root: InlineComment; replies: InlineComment[] }[] = [];
    const threadMap = new Map<number | string, (typeof threads)[0]>();

    for (const c of fileComments) {
      if (c.in_reply_to_id && threadMap.has(c.in_reply_to_id)) {
        const t = threadMap.get(c.in_reply_to_id)!;
        t.replies.push(c);
        threadMap.set(c.id, t);
      } else {
        const t = { root: c, replies: [] as InlineComment[] };
        threads.push(t);
        threadMap.set(c.id, t);
      }
    }

    const result = new Map<string, (typeof threads)>();
    for (const t of threads) {
      const lineNo = t.root.line ?? 0;
      const side = (t.root.side ?? "RIGHT").toUpperCase();
      const key = `${lineNo}:${side}`;
      if (!result.has(key)) result.set(key, []);
      result.get(key)!.push(t);
    }
    return result;
  }, [existingComments, selectedFile]);

  const clearSelection = useCallback(() => {
    setAnchor(null);
    setEnd(null);
  }, []);

  useEffect(() => {
    clearSelection();
  }, [selectedFile, clearSelection]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") clearSelection();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [clearSelection]);

  const rangeStart = anchor && end
    ? (anchor.globalIdx <= end.globalIdx ? anchor : end)
    : anchor;
  const rangeEnd = anchor && end
    ? (anchor.globalIdx <= end.globalIdx ? end : anchor)
    : anchor;

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

  const handleCommentSubmit = useCallback(
    async (body: string) => {
      if (!onAddComment || !selectedFile || !rangeStart) return;
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
      await onAddComment(params);
      clearSelection();
    },
    [onAddComment, selectedFile, rangeStart, rangeEnd, end, clearSelection],
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
    <div className="flex h-full min-h-0">
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
              <span className="ml-auto shrink-0 text-[10px] text-[var(--o-text-tertiary)]">
                <span className="text-[var(--o-pastel-mint-fg)]">+{f.additions}</span>
                {" "}
                <span className="text-[var(--o-pastel-rose-fg)]">-{f.deletions}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Diff content */}
      <div className="min-w-0 flex-1 overflow-auto bg-[var(--o-bg)]">
        {activeFile && (
          <div className="border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-4 py-2">
            <span className="text-xs font-medium text-[var(--o-text)]">{activeFile.filename}</span>
            <span className="ml-3 text-[11px] text-[var(--o-text-tertiary)]">
              <span className="text-[var(--o-pastel-mint-fg)]">+{activeFile.additions}</span>
              {" "}
              <span className="text-[var(--o-pastel-rose-fg)]">-{activeFile.deletions}</span>
            </span>
          </div>
        )}

        {onAddComment && hunks.length > 0 && (
          <div className="flex items-center gap-2 border-b border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-4 py-1.5 text-[11px] text-[var(--o-text-tertiary)]">
            <Info className="h-3 w-3 shrink-0" />
            {!anchor ? (
              <span>
                Click <Plus className="inline h-3 w-3 rounded border border-current align-text-bottom" /> on a line to add a comment.
                For multi-line: click <Plus className="inline h-3 w-3 rounded border border-current align-text-bottom" /> on the start line, then <kbd className="rounded bg-[var(--o-bg-raised)] px-1 py-0.5 text-[10px] font-medium">Shift</kbd>+click <Plus className="inline h-3 w-3 rounded border border-current align-text-bottom" /> on the end line.
              </span>
            ) : !end ? (
              <span>
                Line {rangeStart?.lineNo} selected.
                {" "}<kbd className="rounded bg-[var(--o-bg-raised)] px-1 py-0.5 text-[10px] font-medium">Shift</kbd>+click <Plus className="inline h-3 w-3 rounded border border-current align-text-bottom" /> on another line to select a range, or write your comment below.
                {" "}Press <kbd className="rounded bg-[var(--o-bg-raised)] px-1 py-0.5 text-[10px] font-medium">Esc</kbd> to cancel.
              </span>
            ) : (
              <span>
                Lines {rangeStart?.lineNo}–{rangeEnd?.lineNo} selected. Write your comment below.
                {" "}Press <kbd className="rounded bg-[var(--o-bg-raised)] px-1 py-0.5 text-[10px] font-medium">Esc</kbd> to cancel.
              </span>
            )}
          </div>
        )}

        {hunks.length > 0 ? (
          <div className="min-w-0 font-mono text-[12px] leading-5">
            {hunks.map((hunk, hi) => (
              <div key={hi}>
                <div className="bg-[var(--o-pastel-sky)] px-4 py-0.5 text-[11px] text-[var(--o-pastel-sky-fg)]">
                  {hunk.header}
                </div>
                <table className="w-full border-collapse">
                  <tbody>
                    {hunk.lines.map((line, li) => {
                      const currentIdx = globalLineIdx++;
                      const lineNo = lineNumber(line);
                      const side = lineSide(line.type);
                      const key = `${lineNo}:${side}`;
                      let lineThreads = threadsByLine.get(key) ?? [];
                      if (line.type === "context" && line.oldLine != null) {
                        const leftThreads = threadsByLine.get(`${line.oldLine}:LEFT`) ?? [];
                        if (leftThreads.length) lineThreads = [...lineThreads, ...leftThreads];
                      }

                      const inRange =
                        rangeStart && rangeEnd
                          ? currentIdx >= rangeStart.globalIdx && currentIdx <= rangeEnd.globalIdx
                          : false;
                      const isAnchorLine = anchor?.globalIdx === currentIdx;
                      const showForm = showFormAfterIdx === currentIdx && anchor !== null;

                      return (
                        <React.Fragment key={`${hi}-${li}`}>
                          <tr className="group">
                            {/* Plus button gutter */}
                            {onAddComment && (
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
                                  title={anchor ? "Shift+click to select range end" : "Add comment"}
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
                                line.type === "context" && !inRange && "text-[var(--o-text-secondary)]",
                                inRange && "text-[var(--o-text)]",
                              )}
                            >
                              {line.content}
                              {lineThreads.map((thread) => (
                                <InlineThread
                                  key={thread.root.id}
                                  thread={thread}
                                  onReply={onReplyComment}
                                />
                              ))}
                            </td>
                          </tr>
                          {showForm && (
                            <tr>
                              <td colSpan={onAddComment ? 5 : 4} className="px-2 py-1">
                                <CommentForm
                                  onSubmit={handleCommentSubmit}
                                  onCancel={clearSelection}
                                />
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ))}
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
    </div>
  );
}

export type { DiffFile };
