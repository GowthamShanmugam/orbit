import { streamThreadChat } from "@/api/threads";
import { useSessionStore } from "@/stores/sessionStore";
import {
  useThreadStore,
  nextThreadActionId,
} from "@/stores/threadStore";
import type { ActivityIcon, StreamEvent } from "@/types";
import clsx from "clsx";
import { ArrowLeft, GitBranch, Send, Square, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ActivityStream from "./ActivityStream/ActivityStream";

// ---------------------------------------------------------------------------
// Markdown renderer (same as ChatPanel's AssistantMarkdown)
// ---------------------------------------------------------------------------

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <div className="space-y-1 break-words text-[13px] leading-relaxed text-[var(--o-text)]">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-2 mt-4 text-base font-bold text-[var(--o-text)]">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-3 text-[14px] font-bold text-[var(--o-text)]">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1 mt-2 text-[13px] font-semibold text-[var(--o-text)]">
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="my-1.5 text-[13px] leading-relaxed">{children}</p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-[var(--o-text)]">
              {children}
            </strong>
          ),
          em: ({ children }) => (
            <em className="italic text-[var(--o-text-link)]">{children}</em>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-[var(--o-accent)] underline decoration-[var(--o-accent)]/30 underline-offset-2 hover:text-[var(--o-accent-hover)] hover:decoration-[var(--o-accent-hover)]"
            >
              {children}
            </a>
          ),
          ul: ({ children }) => (
            <ul className="my-1.5 list-disc space-y-0.5 pl-5 text-[13px]">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="my-1.5 list-decimal space-y-0.5 pl-5 text-[13px]">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="leading-relaxed">{children}</li>
          ),
          hr: () => <hr className="my-3 border-[var(--o-border)]" />,
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-[var(--o-accent)]/30 pl-3 text-[var(--o-text-secondary)]">
              {children}
            </blockquote>
          ),
          code: ({ className, children }) => {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              const lang = className?.replace("language-", "") ?? "";
              return (
                <div className="group relative my-2">
                  {lang && (
                    <span className="absolute right-2.5 top-2 rounded bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-[var(--o-text-tertiary)]">
                      {lang}
                    </span>
                  )}
                  <pre className="overflow-x-auto rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] p-3 text-[11px] leading-relaxed text-[var(--o-text)]">
                    <code>{children}</code>
                  </pre>
                </div>
              );
            }
            return (
              <code className="rounded-md bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[11px] text-[var(--o-accent)]">
                {children}
              </code>
            );
          },
          pre: ({ children }) => <>{children}</>,
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto rounded-lg border border-[var(--o-border)]">
              <table className="w-full border-collapse text-[12px]">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="border-b border-[var(--o-border)] bg-[var(--o-bg-raised)]">
              {children}
            </thead>
          ),
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => (
            <tr className="border-b border-[var(--o-border)]/50">
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th className="px-3 py-2 text-left font-semibold text-[var(--o-text)]">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 text-[var(--o-text-secondary)]">
              {children}
            </td>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ThreadPanel
// ---------------------------------------------------------------------------

interface ThreadPanelProps {
  projectId: string;
  sessionId: string;
}

export default function ThreadPanel({ projectId, sessionId }: ThreadPanelProps) {
  const activeThread = useThreadStore((s) => s.activeThread);
  const parentMessage = useThreadStore((s) => s.parentMessage);
  const threadMessages = useThreadStore((s) => s.threadMessages);
  const addThreadMessage = useThreadStore((s) => s.addThreadMessage);
  const closeThread = useThreadStore((s) => s.closeThread);
  const registerThread = useThreadStore((s) => s.registerThread);

  const isStreaming = useThreadStore((s) => s.isStreaming);
  const streamingText = useThreadStore((s) => s.streamingText);
  const setStreaming = useThreadStore((s) => s.setStreaming);
  const appendStreamText = useThreadStore((s) => s.appendStreamText);
  const resetStreamText = useThreadStore((s) => s.resetStreamText);
  const threadActions = useThreadStore((s) => s.actions);
  const addAction = useThreadStore((s) => s.addAction);
  const updateAction = useThreadStore((s) => s.updateAction);
  const clearActions = useThreadStore((s) => s.clearActions);

  const sessionModel = useSessionStore((s) => s.currentSession?.model);

  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [threadMessages.length, streamingText]);

  const handleStream = useCallback(
    async (text: string) => {
      if (!activeThread) return;
      clearActions();
      resetStreamText();
      setStreaming(true);

      const model = sessionModel || undefined;
      const actionIds = new Map<string, string>();

      try {
        for await (const event of streamThreadChat(
          projectId,
          sessionId,
          activeThread.id,
          { message: text, model },
        )) {
          switch (event.type) {
            case "user_message": {
              const msg = event as StreamEvent & {
                id: string;
                content: string;
              };
              addThreadMessage({
                id: msg.id,
                session_id: sessionId,
                thread_id: activeThread.id,
                role: "user",
                content: msg.content as string,
                created_at: new Date().toISOString(),
              });
              break;
            }
            case "activity": {
              const label = event.action as string;
              const status = event.status as
                | "done"
                | "running"
                | "pending";
              const icon = (event.icon as string) ?? "dot";
              const key = label;
              if (actionIds.has(key)) {
                updateAction(actionIds.get(key)!, { status });
              } else {
                const id = nextThreadActionId();
                actionIds.set(key, id);
                addAction({
                  id,
                  icon: icon as ActivityIcon,
                  label,
                  status,
                });
              }
              break;
            }
            case "text_delta": {
              appendStreamText(event.text as string);
              break;
            }
            case "message_complete": {
              const mc = event as StreamEvent & {
                message_id: string;
                content: string;
              };
              addThreadMessage({
                id: mc.message_id,
                session_id: sessionId,
                thread_id: activeThread.id,
                role: "assistant",
                content: mc.content as string,
                created_at: new Date().toISOString(),
              });
              resetStreamText();
              // Update reply count in the thread registry
              registerThread({
                ...activeThread,
                reply_count: threadMessages.length + 2,
              });
              break;
            }
            case "error": {
              const errId = nextThreadActionId();
              addAction({
                id: errId,
                icon: "dot",
                label: `Error: ${event.message}`,
                status: "done",
              });
              break;
            }
            case "done":
              break;
          }
        }
      } catch (err) {
        const errId = nextThreadActionId();
        addAction({
          id: errId,
          icon: "dot",
          label: `Stream error: ${(err as Error).message}`,
          status: "done",
        });
      } finally {
        setStreaming(false);
      }
    },
    [
      projectId,
      sessionId,
      activeThread,
      sessionModel,
      threadMessages.length,
      addThreadMessage,
      clearActions,
      resetStreamText,
      setStreaming,
      appendStreamText,
      addAction,
      updateAction,
      registerThread,
    ],
  );

  const onSubmit = useCallback(() => {
    const text = draft.trim();
    if (!text || isStreaming) return;
    setDraft("");
    handleStream(text);
  }, [draft, isStreaming, handleStream]);

  if (!activeThread || !parentMessage) return null;

  const parentSnippet =
    parentMessage.content.length > 120
      ? parentMessage.content.slice(0, 120) + "..."
      : parentMessage.content;

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-[var(--o-bg-overlay)]">
      {/* Header */}
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-[var(--o-border)] px-3">
        <button
          type="button"
          onClick={closeThread}
          className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          aria-label="Close thread"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </button>
        <GitBranch className="h-3.5 w-3.5 shrink-0 text-[var(--o-accent)]" />
        <h2 className="min-w-0 flex-1 truncate text-[13px] font-semibold text-[var(--o-text)]">
          Thread
        </h2>
        <button
          type="button"
          onClick={closeThread}
          className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          aria-label="Close thread"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <ActivityStream actions={threadActions} isStreaming={isStreaming} />

      {/* Message list */}
      <div
        ref={listRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
      >
        {/* Parent message (context) */}
        <div className="rounded-lg border border-dashed border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-3 py-2 opacity-70">
          <div className="mb-1 flex items-center gap-1.5">
            <GitBranch className="h-3 w-3 text-[var(--o-accent)]" />
            <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
              Branched from
            </span>
          </div>
          <p className="text-[12px] leading-relaxed text-[var(--o-text-secondary)]">
            {parentSnippet}
          </p>
        </div>

        {threadMessages.length === 0 && !isStreaming && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
            <p className="text-[13px] text-[var(--o-text-secondary)]">
              Ask a follow-up question about this response.
            </p>
            <p className="max-w-[220px] text-[11px] leading-relaxed text-[var(--o-text-tertiary)]">
              This thread has the full conversation context up to the
              branched message.
            </p>
          </div>
        )}

        {threadMessages.map((m) => (
          <div
            key={m.id}
            className={clsx(
              "flex",
              m.role === "user" ? "justify-end" : "justify-start",
            )}
          >
            <div
              className={clsx(
                "max-w-[92%] overflow-hidden rounded-xl px-3.5 py-2.5",
                m.role === "user"
                  ? "bg-[var(--o-user-bubble)] text-[var(--o-text)] ring-1 ring-[var(--o-user-ring)]"
                  : "bg-[var(--o-bg-raised)] text-[var(--o-text)] ring-1 ring-[var(--o-border)]",
              )}
              style={{ boxShadow: "var(--o-shadow-sm)" }}
            >
              {m.role === "assistant" || m.role === "system" ? (
                <AssistantMarkdown content={m.content} />
              ) : (
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed">
                  {m.content}
                </p>
              )}
            </div>
          </div>
        ))}

        {isStreaming && streamingText && (
          <div className="flex justify-start">
            <div
              className="max-w-[92%] overflow-hidden rounded-xl bg-[var(--o-bg-raised)] px-3.5 py-2.5 ring-1 ring-[var(--o-border)]"
              style={{ boxShadow: "var(--o-shadow-sm)" }}
            >
              <AssistantMarkdown content={streamingText} />
              <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-[var(--o-accent)] align-text-bottom" />
            </div>
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-[var(--o-border)] bg-[var(--o-bg-raised)] p-3">
        <div className="flex gap-2 rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-input)] p-2.5 transition-all focus-within:border-[var(--o-accent)] focus-within:shadow-[0_0_0_3px_var(--o-accent-muted)]">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
            rows={2}
            placeholder="Ask about this response..."
            className="min-h-[48px] flex-1 resize-none bg-transparent text-[13px] leading-relaxed text-[var(--o-text)] outline-none placeholder:text-[var(--o-text-tertiary)]"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={() => setStreaming(false)}
              className="o-btn-icon h-8 w-8 self-end bg-[var(--o-danger)] text-white hover:bg-[var(--o-danger-bg)]"
              style={{ boxShadow: "var(--o-shadow-sm)" }}
              aria-label="Stop generating"
            >
              <Square className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onSubmit}
              disabled={!draft.trim()}
              className={clsx(
                "o-btn-icon h-8 w-8 self-end",
                draft.trim()
                  ? "bg-[var(--o-accent)] text-white hover:bg-[var(--o-accent-hover)]"
                  : "cursor-not-allowed bg-[var(--o-bg-subtle)] text-[var(--o-text-tertiary)]",
              )}
              style={
                draft.trim()
                  ? { boxShadow: "var(--o-shadow-sm)" }
                  : undefined
              }
              aria-label="Send message"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
