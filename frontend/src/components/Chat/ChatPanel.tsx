import { sendMessage } from "@/api/sessions";
import { useSessionStore } from "@/stores/sessionStore";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, Send } from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import ActivityStream from "./ActivityStream/ActivityStream";

const MODELS = [
  "Claude Sonnet 4",
  "Claude Opus 4",
  "Claude Haiku 3.5",
] as const;

function renderBoldSegment(text: string, keyBase: string): React.ReactNode {
  const parts = text.split(/(\*\*.+?\*\*)/g);
  return parts.map((part, i) => {
    const m = part.match(/^\*\*(.+?)\*\*$/);
    if (m) {
      return (
        <strong key={`${keyBase}-b-${i}`} className="font-semibold text-[#e6edf3]">
          {m[1]}
        </strong>
      );
    }
    return <Fragment key={`${keyBase}-t-${i}`}>{part}</Fragment>;
  });
}

function AssistantMarkdown({ content }: { content: string }) {
  const lines = content.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trimStart();
    if (trimmed.startsWith("```")) {
      i += 1;
      const code: string[] = [];
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      blocks.push(
        <pre
          key={`blk-${key++}`}
          className="overflow-x-auto rounded-md border border-[#30363d] bg-[#0d1117] p-3 text-[11px] leading-relaxed text-[#e6edf3]"
        >
          <code>{code.join("\n")}</code>
        </pre>
      );
      continue;
    }
    if (/^\s*[-*]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul
          key={`blk-${key++}`}
          className="list-disc space-y-1 pl-4 text-[13px] leading-relaxed"
        >
          {items.map((t, j) => (
            <li key={j}>{renderBoldSegment(t, `li-${key}-${j}`)}</li>
          ))}
        </ul>
      );
      continue;
    }
    if (trimmed === "") {
      i += 1;
      continue;
    }
    const para: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trimStart().startsWith("```") &&
      !/^\s*[-*]\s/.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    blocks.push(
      <p
        key={`blk-${key++}`}
        className="text-[13px] leading-relaxed text-[#e6edf3]"
      >
        {renderBoldSegment(para.join(" "), `p-${key}`)}
      </p>
    );
  }
  return <div className="space-y-2">{blocks}</div>;
}

interface ChatPanelProps {
  projectId: string;
  sessionId: string;
}

export default function ChatPanel({ projectId, sessionId }: ChatPanelProps) {
  const messages = useSessionStore((s) => s.messages);
  const [model, setModel] = useState<string>(MODELS[0]);
  const [draft, setDraft] = useState("");
  const [modelOpen, setModelOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const sendMut = useMutation({
    mutationFn: (content: string) =>
      sendMessage(projectId, sessionId, { content }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["messages", projectId, sessionId],
      });
    },
  });

  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, sendMut.isPending]);

  const onSubmit = useCallback(() => {
    const text = draft.trim();
    if (!text || sendMut.isPending) return;
    setDraft("");
    sendMut.mutate(text);
  }, [draft, sendMut]);

  useEffect(() => {
    function onDocClick() {
      setModelOpen(false);
    }
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  return (
    <div className="flex h-full min-h-0 w-[380px] shrink-0 flex-col border-l border-[#30363d] bg-[#1c2128]">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-[#30363d] px-3">
        <h2 className="text-sm font-semibold text-[#e6edf3]">Chat</h2>
        <div className="relative">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setModelOpen((o) => !o);
            }}
            className="flex h-8 max-w-[160px] items-center gap-1 rounded-md border border-[#30363d] bg-[#161b22] px-2 text-left text-[11px] text-[#e6edf3] transition-colors hover:border-[#484f58]"
          >
            <span className="truncate">{model}</span>
            <ChevronDown className="h-3 w-3 shrink-0 text-[#8b949e]" />
          </button>
          {modelOpen && (
            <div
              className="absolute right-0 top-full z-20 mt-1 w-48 overflow-hidden rounded-md border border-[#30363d] bg-[#161b22] py-1 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              {MODELS.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => {
                    setModel(m);
                    setModelOpen(false);
                  }}
                  className={clsx(
                    "flex w-full px-3 py-1.5 text-left text-[11px] transition-colors hover:bg-[#21262d]",
                    m === model ? "text-[#58a6ff]" : "text-[#e6edf3]"
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <ActivityStream />
      <div
        ref={listRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
      >
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 py-12 text-center">
            <p className="text-sm font-medium text-[#8b949e]">
              No messages yet
            </p>
            <p className="max-w-[240px] text-xs leading-relaxed text-[#6e7681]">
              Ask Orbit to explore the codebase, draft a change, or explain an
              error. Messages appear here.
            </p>
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={clsx(
              "flex",
              m.role === "user" ? "justify-end" : "justify-start"
            )}
          >
            <div
              className={clsx(
                "max-w-[92%] rounded-lg px-3 py-2 shadow-sm",
                m.role === "user"
                  ? "bg-[#1f6feb]/25 text-[#e6edf3] ring-1 ring-[#388bfd]/40"
                  : "bg-[#161b22] text-[#e6edf3] ring-1 ring-[#30363d]"
              )}
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
      </div>
      <div className="shrink-0 border-t border-[#30363d] bg-[#161b22] p-3">
        <div className="flex gap-2 rounded-md border border-[#30363d] bg-[#0d1117] p-2 focus-within:border-[#58a6ff]/50">
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
            placeholder="Message Orbit…"
            className="min-h-[72px] flex-1 resize-none bg-transparent text-[13px] leading-relaxed text-[#e6edf3] outline-none placeholder:text-[#6e7681]"
          />
          <button
            type="button"
            onClick={onSubmit}
            disabled={!draft.trim() || sendMut.isPending}
            className={clsx(
              "flex h-9 w-9 shrink-0 items-center justify-center self-end rounded-md transition-colors",
              draft.trim() && !sendMut.isPending
                ? "bg-[#238636] text-white hover:bg-[#2ea043]"
                : "cursor-not-allowed bg-[#21262d] text-[#484f58]"
            )}
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        {sendMut.isError && (
          <p className="mt-2 text-xs text-[#f85149]">
            {(sendMut.error as Error)?.message ?? "Failed to send"}
          </p>
        )}
      </div>
    </div>
  );
}
