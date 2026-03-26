import { streamChat } from "@/api/ai";
import { scanForSecrets } from "@/api/secrets";
import { updateSession } from "@/api/sessions";
import { useActivityStore, nextActionId } from "@/stores/activityStore";
import { useSecretStore } from "@/stores/secretStore";
import { useSessionStore } from "@/stores/sessionStore";
import type { ActivityIcon, StreamEvent } from "@/types";
import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, Send, Square } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ActivityStream from "./ActivityStream/ActivityStream";

const INITIAL_VISIBLE = 10;
const LOAD_MORE_STEP = 10;

const MODELS = [
  { id: "claude-opus-4-6", label: "Claude Opus 4.6" },
  { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
  { id: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
] as const;

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <div className="space-y-1 break-words text-[13px] leading-relaxed text-[var(--o-text)]">
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => <h1 className="mb-2 mt-4 text-base font-bold text-[var(--o-text)]">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-3 text-[14px] font-bold text-[var(--o-text)]">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-1 mt-2 text-[13px] font-semibold text-[var(--o-text)]">{children}</h3>,
        p: ({ children }) => <p className="my-1.5 text-[13px] leading-relaxed">{children}</p>,
        strong: ({ children }) => <strong className="font-semibold text-[var(--o-text)]">{children}</strong>,
        em: ({ children }) => <em className="italic text-[var(--o-text-link)]">{children}</em>,
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer" className="text-[var(--o-accent)] underline decoration-[var(--o-accent)]/30 underline-offset-2 hover:text-[var(--o-accent-hover)] hover:decoration-[var(--o-accent-hover)]">
            {children}
          </a>
        ),
        ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5 text-[13px]">{children}</ul>,
        ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5 text-[13px]">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        hr: () => <hr className="my-3 border-[var(--o-border)]" />,
        blockquote: ({ children }) => (
          <blockquote className="my-2 border-l-2 border-[var(--o-accent)]/30 pl-3 text-[var(--o-text-secondary)]">{children}</blockquote>
        ),
        code: ({ className, children }) => {
          const isBlock = className?.includes("language-");
          if (isBlock) {
            const lang = className?.replace("language-", "") ?? "";
            return (
              <div className="group relative my-2">
                {lang && <span className="absolute right-2.5 top-2 rounded bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-[var(--o-text-tertiary)]">{lang}</span>}
                <pre className="overflow-x-auto rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] p-3 text-[11px] leading-relaxed text-[var(--o-text)]">
                  <code>{children}</code>
                </pre>
              </div>
            );
          }
          return (
            <code className="rounded-md bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[11px] text-[var(--o-accent)]">{children}</code>
          );
        },
        pre: ({ children }) => <>{children}</>,
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto rounded-lg border border-[var(--o-border)]">
            <table className="w-full border-collapse text-[12px]">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="border-b border-[var(--o-border)] bg-[var(--o-bg-raised)]">{children}</thead>,
        tbody: ({ children }) => <tbody>{children}</tbody>,
        tr: ({ children }) => <tr className="border-b border-[var(--o-border)]/50">{children}</tr>,
        th: ({ children }) => <th className="px-3 py-2 text-left font-semibold text-[var(--o-text)]">{children}</th>,
        td: ({ children }) => <td className="px-3 py-2 text-[var(--o-text-secondary)]">{children}</td>,
      }}
    >
      {content}
    </Markdown>
    </div>
  );
}

interface ChatPanelProps {
  projectId: string;
  sessionId: string;
}

export default function ChatPanel({ projectId, sessionId }: ChatPanelProps) {
  const messages = useSessionStore((s) => s.messages);
  const addMessage = useSessionStore((s) => s.addMessage);
  const sessionModel = useSessionStore((s) => s.currentSession?.model);
  const [model, setModelLocal] = useState<string>(sessionModel || MODELS[0].id);
  const [draft, setDraft] = useState("");
  const [modelOpen, setModelOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const isStreaming = useActivityStore((s) => s.isStreaming);
  const streamingText = useActivityStore((s) => s.streamingText);
  const setStreaming = useActivityStore((s) => s.setStreaming);
  const appendStreamText = useActivityStore((s) => s.appendStreamText);
  const resetStreamText = useActivityStore((s) => s.resetStreamText);
  const addAction = useActivityStore((s) => s.addAction);
  const updateAction = useActivityStore((s) => s.updateAction);
  const clearActions = useActivityStore((s) => s.clearActions);
  const setScanWarnings = useSecretStore((s) => s.setScanWarnings);

  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);

  useEffect(() => {
    if (sessionModel) setModelLocal(sessionModel);
  }, [sessionModel]);

  const setModel = useCallback(
    (newModel: string) => {
      setModelLocal(newModel);
      updateSession(projectId, sessionId, { model: newModel }).then(() => {
        queryClient.invalidateQueries({ queryKey: ["session", projectId, sessionId] });
      });
    },
    [projectId, sessionId, queryClient],
  );

  useEffect(() => {
    setVisibleCount(INITIAL_VISIBLE);
  }, [sessionId]);

  const hiddenCount = Math.max(0, messages.length - visibleCount);
  const visibleMessages = useMemo(
    () => (hiddenCount > 0 ? messages.slice(-visibleCount) : messages),
    [messages, hiddenCount, visibleCount],
  );

  const loadEarlier = useCallback(() => {
    setVisibleCount((v) => v + LOAD_MORE_STEP);
  }, []);

  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, streamingText]);

  const handleStream = useCallback(
    async (text: string) => {
      clearActions();
      resetStreamText();
      setStreaming(true);

      const scanResult = await scanForSecrets(text).catch(() => null);
      if (scanResult?.has_secrets) {
        setScanWarnings(scanResult.matches);
      }

      const actionIds = new Map<string, string>();

      try {
        for await (const event of streamChat(projectId, sessionId, {
          message: text,
          model,
        })) {
          switch (event.type) {
            case "user_message": {
              const msg = event as StreamEvent & { id: string; content: string };
              addMessage({
                id: msg.id,
                session_id: sessionId,
                role: "user",
                content: msg.content as string,
                created_at: new Date().toISOString(),
              });
              break;
            }
            case "activity": {
              const label = event.action as string;
              const status = event.status as "done" | "running" | "pending";
              const icon = (event.icon as string) ?? "dot";
              const key = label;
              if (actionIds.has(key)) {
                updateAction(actionIds.get(key)!, { status });
              } else {
                const id = nextActionId();
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
              addMessage({
                id: mc.message_id,
                session_id: sessionId,
                role: "assistant",
                content: mc.content as string,
                created_at: new Date().toISOString(),
              });
              resetStreamText();
              break;
            }
            case "error": {
              const errId = nextActionId();
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
        const errId = nextActionId();
        addAction({
          id: errId,
          icon: "dot",
          label: `Stream error: ${(err as Error).message}`,
          status: "done",
        });
      } finally {
        setStreaming(false);
        queryClient.invalidateQueries({
          queryKey: ["messages", projectId, sessionId],
        });
      }
    },
    [
      projectId,
      sessionId,
      model,
      addMessage,
      clearActions,
      resetStreamText,
      setStreaming,
      appendStreamText,
      addAction,
      updateAction,
      setScanWarnings,
      queryClient,
    ],
  );

  const onSubmit = useCallback(() => {
    const text = draft.trim();
    if (!text || isStreaming) return;
    setDraft("");
    handleStream(text);
  }, [draft, isStreaming, handleStream]);

  const onStop = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, [setStreaming]);

  useEffect(() => {
    function onDocClick() { setModelOpen(false); }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  const selectedLabel =
    MODELS.find((m) => m.id === model)?.label ?? MODELS[0].label;

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-[var(--o-bg-overlay)]">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-[var(--o-border)] px-3">
        <h2 className="text-[13px] font-semibold text-[var(--o-text)]">Chat</h2>
        <div className="relative">
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setModelOpen((o) => !o); }}
            className="flex h-7 max-w-[160px] items-center gap-1.5 rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-2 text-left text-[11px] text-[var(--o-text-secondary)] transition-all hover:border-[var(--o-border-subtle)] hover:text-[var(--o-text)]"
          >
            <span className="truncate">{selectedLabel}</span>
            <ChevronDown className="h-3 w-3 shrink-0 opacity-60" />
          </button>
          {modelOpen && (
            <div
              className="o-dropdown absolute right-0 top-full z-20 mt-1 w-56 py-1"
              onClick={(e) => e.stopPropagation()}
            >
              {MODELS.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => { setModel(m.id); setModelOpen(false); }}
                  className={clsx(
                    "flex w-full flex-col px-3 py-2 text-left transition-colors",
                    m.id === model
                      ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                      : "text-[var(--o-text)] hover:bg-[var(--o-bg-subtle)]",
                  )}
                >
                  <span className="text-[11px] font-medium">{m.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <ActivityStream />

      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && !isStreaming && (
          <div className="flex h-full flex-col items-center justify-center gap-3 py-12 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--o-accent-muted)]" style={{ backgroundImage: "var(--o-gradient-card)" }}>
              <Send className="h-5 w-5 text-[var(--o-accent)]" />
            </div>
            <div>
              <p className="text-sm font-medium text-[var(--o-text-secondary)]">No messages yet</p>
              <p className="mt-1 max-w-[240px] text-xs leading-relaxed text-[var(--o-text-tertiary)]">
                Ask Orbit to explore the codebase, draft a change, or explain an error.
              </p>
            </div>
          </div>
        )}
        {hiddenCount > 0 && (
          <button
            type="button"
            onClick={loadEarlier}
            className="o-btn-ghost mx-auto flex items-center gap-1.5 rounded-full border border-[var(--o-border)] px-3 py-1 text-[11px]"
          >
            Load {Math.min(hiddenCount, LOAD_MORE_STEP)} earlier messages
          </button>
        )}
        {visibleMessages.map((m) => (
          <div
            key={m.id}
            className={clsx("flex", m.role === "user" ? "justify-end" : "justify-start")}
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
            <div className="max-w-[92%] overflow-hidden rounded-xl bg-[var(--o-bg-raised)] px-3.5 py-2.5 ring-1 ring-[var(--o-border)]" style={{ boxShadow: "var(--o-shadow-sm)" }}>
              <AssistantMarkdown content={streamingText} />
              <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-[var(--o-accent)] align-text-bottom" />
            </div>
          </div>
        )}
      </div>

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
            rows={3}
            placeholder="Message Orbit..."
            className="min-h-[72px] flex-1 resize-none bg-transparent text-[13px] leading-relaxed text-[var(--o-text)] outline-none placeholder:text-[var(--o-text-tertiary)]"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
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
              style={draft.trim() ? { boxShadow: "var(--o-shadow-sm)" } : undefined}
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
