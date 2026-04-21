import { confirmTool } from "@/api/ai";
import { listProjectSkills } from "@/api/skills";
import { streamThreadChat, updateThread } from "@/api/threads";
import { useSessionStore } from "@/stores/sessionStore";
import { useThreadStore, nextThreadActionId } from "@/stores/threadStore";
import type { ActivityIcon, PluginSkill, StreamEvent } from "@/types";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Check, ChevronDown, GitBranch, MessageSquare, Send, ShieldAlert, Sparkles, Square, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ActivityStream from "./ActivityStream/ActivityStream";

const MODELS = [
  { id: "claude-opus-4-6", label: "Opus 4.6" },
  { id: "claude-sonnet-4-6", label: "Sonnet 4.6" },
  { id: "claude-sonnet-4-5-20250929", label: "Sonnet 4.5" },
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5" },
] as const;

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
            <h1 className="mb-2 mt-4 text-base font-bold text-[var(--o-text)]">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-3 text-[14px] font-bold text-[var(--o-text)]">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1 mt-2 text-[13px] font-semibold text-[var(--o-text)]">{children}</h3>
          ),
          p: ({ children }) => <p className="my-1.5 text-[13px] leading-relaxed">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-[var(--o-text)]">{children}</strong>
          ),
          em: ({ children }) => <em className="italic text-[var(--o-text-link)]">{children}</em>,
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
            <ul className="my-1.5 list-disc space-y-0.5 pl-5 text-[13px]">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="my-1.5 list-decimal space-y-0.5 pl-5 text-[13px]">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
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
              <table className="w-full border-collapse text-[12px]">{children}</table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="border-b border-[var(--o-border)] bg-[var(--o-bg-raised)]">
              {children}
            </thead>
          ),
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => (
            <tr className="border-b border-[var(--o-border)]/50">{children}</tr>
          ),
          th: ({ children }) => (
            <th className="px-3 py-2 text-left font-semibold text-[var(--o-text)]">{children}</th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 text-[var(--o-text-secondary)]">{children}</td>
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
  const sessionAiConfig = useSessionStore((s) => s.currentSession?.ai_config);

  const threadModel = activeThread?.claude_model ?? null;
  const threadAiConfig = activeThread?.ai_config ?? null;
  const effectiveModel = threadModel || sessionModel || MODELS[0].id;
  const effectiveSkillSlug = (threadAiConfig as Record<string, string> | null)?.skill
    ?? (sessionAiConfig as Record<string, string> | null)?.skill
    ?? null;

  const { data: skillData } = useQuery({
    queryKey: ["project-skills", projectId],
    queryFn: () => listProjectSkills(projectId),
  });

  const allSkills: (PluginSkill & { packName: string })[] = useMemo(
    () =>
      (skillData?.skills ?? []).flatMap((pack) =>
        pack.skills
          .filter((s) => s.user_invocable)
          .map((s) => ({ ...s, packName: pack.name })),
      ),
    [skillData],
  );

  const currentSkill = effectiveSkillSlug ? allSkills.find((s) => s.slug === effectiveSkillSlug) : null;

  const [modelOpen, setModelOpen] = useState(false);
  const [skillOpen, setSkillOpen] = useState(false);
  const [draft, setDraft] = useState("");

  const persistThreadConfig = useCallback(
    async (patch: { claude_model?: string; ai_config?: Record<string, unknown> }) => {
      if (!activeThread) return;
      try {
        const updated = await updateThread(projectId, sessionId, activeThread.id, patch);
        registerThread(updated);
      } catch { /* non-fatal */ }
    },
    [projectId, sessionId, activeThread, registerThread],
  );

  const selectModel = useCallback(
    (id: string) => {
      setModelOpen(false);
      persistThreadConfig({ claude_model: id });
    },
    [persistThreadConfig],
  );

  const selectSkill = useCallback(
    (slug: string | null) => {
      setSkillOpen(false);
      persistThreadConfig({ ai_config: { skill: slug } });
    },
    [persistThreadConfig],
  );

  useEffect(() => {
    if (!modelOpen && !skillOpen) return;
    const onPointerDown = () => { setModelOpen(false); setSkillOpen(false); };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [modelOpen, skillOpen]);
  const listRef = useRef<HTMLDivElement>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<{
    toolId: string;
    toolName: string;
    toolInput: Record<string, unknown>;
    description: string;
  } | null>(null);

  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [threadMessages.length, streamingText, pendingConfirmation]);

  const handleStream = useCallback(
    async (text: string) => {
      if (!activeThread) return;
      clearActions();
      resetStreamText();
      setStreaming(true);

      const model = effectiveModel || undefined;
      const actionIds = new Map<string, string>();

      try {
        for await (const event of streamThreadChat(projectId, sessionId, activeThread.id, {
          message: text,
          model,
        })) {
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
              const status = event.status as "done" | "running" | "pending";
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
            case "tool_confirmation": {
              const tc = event as StreamEvent & {
                tool_id: string;
                tool_name: string;
                tool_input: Record<string, unknown>;
                description: string;
              };
              setPendingConfirmation({
                toolId: tc.tool_id,
                toolName: tc.tool_name,
                toolInput: tc.tool_input,
                description: tc.description,
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
      effectiveModel,
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

  const handleToolConfirmation = useCallback(
    async (approved: boolean) => {
      if (!pendingConfirmation) return;
      setPendingConfirmation(null);
      try {
        await confirmTool(projectId, sessionId, pendingConfirmation.toolId, approved);
      } catch {
        /* API failure is non-fatal */
      }
    },
    [projectId, sessionId, pendingConfirmation],
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
      {/* Header — model selector in top bar (same as main chat) */}
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
        <div className="relative" onPointerDown={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={() => { setModelOpen((o) => !o); setSkillOpen(false); }}
            className="flex h-7 max-w-[160px] items-center gap-1.5 rounded-md border border-[var(--o-border)] bg-[var(--o-bg)] px-2 text-left text-[11px] text-[var(--o-text-secondary)] transition-all hover:border-[var(--o-border-subtle)] hover:text-[var(--o-text)]"
          >
            <span className="truncate">{MODELS.find((m) => m.id === effectiveModel)?.label ?? effectiveModel}</span>
            <ChevronDown className="h-3 w-3 shrink-0 opacity-60" />
          </button>
          {modelOpen && (
            <div className="o-dropdown absolute right-0 top-full z-50 mt-1 w-56 py-1">
              {MODELS.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => selectModel(m.id)}
                  className={clsx(
                    "flex w-full flex-col px-3 py-2 text-left transition-colors",
                    m.id === effectiveModel
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
      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
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
              This thread has the full conversation context up to the branched message.
            </p>
          </div>
        )}

        {threadMessages.map((m) => (
          <div
            key={m.id}
            className={clsx("flex gap-2", m.role === "user" ? "justify-end" : "justify-start")}
          >
            {m.role !== "user" && (
              <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--o-pastel-mint)] text-[9px] font-bold text-[var(--o-pastel-mint-fg)]">
                AI
              </span>
            )}
            <div
              className={clsx(
                "max-w-[88%] overflow-hidden rounded-xl px-3.5 py-2.5",
                m.role === "user"
                  ? "bg-[var(--o-user-bubble)] text-[var(--o-text)] ring-1 ring-[var(--o-user-ring)]"
                  : "bg-[var(--o-bg-raised)] text-[var(--o-text)] ring-1 ring-[var(--o-border)]",
              )}
              style={{ boxShadow: "var(--o-shadow-sm)" }}
            >
              {m.role === "assistant" || m.role === "system" ? (
                <AssistantMarkdown content={m.content} />
              ) : (
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{m.content}</p>
              )}
            </div>
            {m.role === "user" && (
              <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--o-pastel-rose)] text-[9px] font-bold text-[var(--o-pastel-rose-fg)]">
                U
              </span>
            )}
          </div>
        ))}

        {pendingConfirmation && (
          <div className="flex gap-2 justify-start">
            <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-500/15 text-amber-600">
              <ShieldAlert className="h-3.5 w-3.5" />
            </span>
            <div className="max-w-[88%] overflow-hidden rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-3 ring-1 ring-amber-500/10">
              <p className="mb-1.5 text-xs font-semibold text-amber-700 dark:text-amber-400">
                Action requires approval
              </p>
              <p className="mb-1 text-[12px] text-[var(--o-text-secondary)]">
                {pendingConfirmation.description}
              </p>
              <pre className="mb-3 max-h-40 overflow-auto rounded-md bg-[var(--o-bg-subtle)] p-2 text-[11px] text-[var(--o-text-secondary)]">
                {JSON.stringify(pendingConfirmation.toolInput, null, 2)}
              </pre>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => handleToolConfirmation(true)}
                  className="flex items-center gap-1.5 rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700"
                >
                  <Check className="h-3.5 w-3.5" /> Approve
                </button>
                <button
                  type="button"
                  onClick={() => handleToolConfirmation(false)}
                  className="flex items-center gap-1.5 rounded-md bg-[var(--o-bg-subtle)] px-3 py-1.5 text-xs font-medium text-[var(--o-text-secondary)] ring-1 ring-[var(--o-border)] hover:bg-[var(--o-bg-raised)]"
                >
                  <X className="h-3.5 w-3.5" /> Reject
                </button>
              </div>
            </div>
          </div>
        )}

        {isStreaming && streamingText && (
          <div className="flex gap-2 justify-start">
            <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--o-pastel-mint)] text-[9px] font-bold text-[var(--o-pastel-mint-fg)]">
              AI
            </span>
            <div
              className="max-w-[88%] overflow-hidden rounded-xl bg-[var(--o-bg-raised)] px-3.5 py-2.5 ring-1 ring-[var(--o-border)]"
              style={{ boxShadow: "var(--o-shadow-sm)" }}
            >
              <AssistantMarkdown content={streamingText} />
              <span className="inline-block h-4 w-1.5 animate-pulse rounded-sm bg-[var(--o-accent)] align-text-bottom" />
            </div>
          </div>
        )}
      </div>

      {/* Composer — skill selector above textarea (same as main chat) */}
      <div className="shrink-0 border-t border-[var(--o-border)] bg-[var(--o-bg-raised)] p-3">
        <div className="mb-2" onPointerDown={(e) => e.stopPropagation()}>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
              Skill
            </span>
            <div className="relative">
              <button
                type="button"
                onClick={() => { setSkillOpen((o) => !o); setModelOpen(false); }}
                className="flex items-center gap-1.5 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-2.5 py-1 text-[11px] font-medium text-[var(--o-text-secondary)] transition-all hover:border-[var(--o-accent)]/40 hover:text-[var(--o-text)]"
              >
                {currentSkill ? (
                  <>
                    <Sparkles className="h-3 w-3 shrink-0 text-[var(--o-green)]" />
                    <span className="max-w-[180px] truncate">{currentSkill.name}</span>
                  </>
                ) : (
                  <>
                    <MessageSquare className="h-3 w-3 shrink-0 text-[var(--o-accent)]" />
                    <span>General Chat</span>
                  </>
                )}
                <ChevronDown className="h-3 w-3 shrink-0 opacity-50" />
              </button>
              {skillOpen && (
                <div className="absolute bottom-full left-0 z-50 mb-1 max-h-60 w-56 overflow-y-auto rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] py-1 shadow-lg">
                  <button
                    type="button"
                    onClick={() => selectSkill(null)}
                    className={clsx(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px]",
                      !effectiveSkillSlug
                        ? "bg-[var(--o-accent-muted)] font-medium text-[var(--o-accent)]"
                        : "text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]",
                    )}
                  >
                    <MessageSquare className="h-3 w-3 shrink-0" />
                    General Chat
                  </button>
                  {allSkills.map((skill) => (
                    <button
                      key={skill.slug}
                      type="button"
                      onClick={() => selectSkill(skill.slug)}
                      className={clsx(
                        "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px]",
                        skill.slug === effectiveSkillSlug
                          ? "bg-[var(--o-accent-muted)] font-medium text-[var(--o-green)]"
                          : "text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)]",
                      )}
                    >
                      <Sparkles className="h-3 w-3 shrink-0" />
                      <span className="truncate">{skill.name}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
        <div
          className="flex gap-2 rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-input)] p-2.5 cursor-text transition-all focus-within:border-[var(--o-accent)] focus-within:shadow-[0_0_0_3px_var(--o-accent-muted)]"
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              const ta = e.currentTarget.querySelector("textarea");
              ta?.focus();
            }
          }}
        >
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
