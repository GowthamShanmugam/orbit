import { useEditorStore } from "@/stores/editorStore";
import { useThemeStore } from "@/stores/themeStore";
import Editor from "@monaco-editor/react";
import clsx from "clsx";
import { Circle, Code, Eye, FileCode, X } from "lucide-react";
import { useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

function isMarkdownFile(path: string) {
  return /\.(md|mdx|markdown)$/i.test(path);
}

function MarkdownPreview({ content }: { content: string }) {
  return (
    <div className="h-full overflow-y-auto bg-[var(--o-bg)] px-10 py-8">
      <article className="mx-auto max-w-3xl space-y-2 text-[14px] leading-relaxed text-[var(--o-text)]">
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => (
              <h1 className="mb-3 mt-6 border-b border-[var(--o-border)] pb-2 text-2xl font-bold text-[var(--o-text)]">
                {children}
              </h1>
            ),
            h2: ({ children }) => (
              <h2 className="mb-2 mt-5 border-b border-[var(--o-border)] pb-1.5 text-xl font-bold text-[var(--o-text)]">
                {children}
              </h2>
            ),
            h3: ({ children }) => (
              <h3 className="mb-1 mt-4 text-lg font-semibold text-[var(--o-text)]">{children}</h3>
            ),
            h4: ({ children }) => (
              <h4 className="mb-1 mt-3 text-base font-semibold text-[var(--o-text)]">{children}</h4>
            ),
            p: ({ children }) => <p className="my-2 leading-relaxed">{children}</p>,
            strong: ({ children }) => (
              <strong className="font-semibold text-[var(--o-text)]">{children}</strong>
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
              <ul className="my-2 list-disc space-y-1 pl-6">{children}</ul>
            ),
            ol: ({ children }) => (
              <ol className="my-2 list-decimal space-y-1 pl-6">{children}</ol>
            ),
            li: ({ children }) => <li className="leading-relaxed">{children}</li>,
            hr: () => <hr className="my-4 border-[var(--o-border)]" />,
            blockquote: ({ children }) => (
              <blockquote className="my-3 border-l-3 border-[var(--o-accent)]/30 pl-4 text-[var(--o-text-secondary)]">
                {children}
              </blockquote>
            ),
            code: ({ className, children }) => {
              const isBlock = className?.includes("language-");
              if (isBlock) {
                const lang = className?.replace("language-", "") ?? "";
                return (
                  <div className="group relative my-3">
                    {lang && (
                      <span className="absolute right-3 top-2.5 rounded bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-[var(--o-text-tertiary)]">
                        {lang}
                      </span>
                    )}
                    <pre className="overflow-x-auto rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-4 text-[12px] leading-relaxed text-[var(--o-text)]">
                      <code>{children}</code>
                    </pre>
                  </div>
                );
              }
              return (
                <code className="rounded-md bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[12px] text-[var(--o-accent)]">
                  {children}
                </code>
              );
            },
            pre: ({ children }) => <>{children}</>,
            table: ({ children }) => (
              <div className="my-3 overflow-x-auto rounded-lg border border-[var(--o-border)]">
                <table className="w-full border-collapse text-[13px]">{children}</table>
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
            img: ({ src, alt }) => (
              <img src={src} alt={alt ?? ""} className="my-3 max-w-full rounded-lg" />
            ),
          }}
        >
          {content}
        </Markdown>
      </article>
    </div>
  );
}

export default function EditorPanel() {
  const tabs = useEditorStore((s) => s.tabs);
  const activeTabId = useEditorStore((s) => s.activeTabId);
  const setActiveTab = useEditorStore((s) => s.setActiveTab);
  const closeTab = useEditorStore((s) => s.closeTab);

  const activeTab = useMemo(() => tabs.find((t) => t.id === activeTabId), [tabs, activeTabId]);
  const isMd = activeTab ? isMarkdownFile(activeTab.path) : false;
  const [mdMode, setMdMode] = useState<"preview" | "source">("preview");

  const editorTheme = useThemeStore((s) => (s.theme === "light" ? "vs" : "vs-dark"));
  const showWelcome = !activeTab;

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-[var(--o-bg)]">
      <div className="flex h-9 shrink-0 items-end border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-1 pt-1">
        <div className="flex min-w-0 flex-1 items-end gap-0 overflow-x-auto">
          {tabs.length === 0 && (
            <div className="flex h-8 shrink-0 items-center gap-2 px-3 text-xs font-medium text-[var(--o-text-tertiary)]">
              <FileCode className="h-3.5 w-3.5 shrink-0" />
              <span>No files open</span>
            </div>
          )}
          {tabs.map((t) => (
            <div
              key={t.id}
              className={clsx(
                "group flex h-8 max-w-[220px] shrink-0 items-center rounded-t-md border border-b-0 text-xs font-medium transition-all duration-150",
                activeTabId === t.id
                  ? "border-[var(--o-border)] bg-[var(--o-bg)] text-[var(--o-text)] -mb-px"
                  : "border-transparent bg-transparent text-[var(--o-text-secondary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]",
              )}
              style={activeTabId === t.id ? { boxShadow: "var(--o-shadow-sm)" } : undefined}
            >
              <button
                type="button"
                onClick={() => setActiveTab(t.id)}
                className="flex min-w-0 flex-1 items-center gap-2 px-3 py-0 text-left"
              >
                <span className="truncate">{t.path.split("/").pop() || t.path}</span>
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(t.id);
                }}
                className="o-btn-icon mr-1 h-5 w-5 rounded text-[var(--o-text-tertiary)] opacity-0 hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)] group-hover:opacity-100"
                aria-label={`Close ${t.path}`}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>

        {isMd && (
          <div className="flex h-8 shrink-0 items-center gap-0.5 border-l border-[var(--o-border)] px-2">
            <button
              type="button"
              title="Preview"
              onClick={() => setMdMode("preview")}
              className={clsx(
                "rounded p-1 transition-colors",
                mdMode === "preview"
                  ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                  : "text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]",
              )}
            >
              <Eye className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="Source"
              onClick={() => setMdMode("source")}
              className={clsx(
                "rounded p-1 transition-colors",
                mdMode === "source"
                  ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                  : "text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]",
              )}
            >
              <Code className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      <div className="relative min-h-0 flex-1">
        {showWelcome ? (
          <div className="flex h-full flex-col items-center justify-center gap-5 px-8 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#195ad2] shadow-lg">
              <Circle className="h-8 w-8 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-[var(--o-text)]">Welcome to Orbit</h2>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-[var(--o-text-secondary)]">
                Click a file in the Explorer to view it here, or ask the AI about your code — file
                references in chat are clickable.
              </p>
            </div>
          </div>
        ) : isMd && mdMode === "preview" ? (
          <MarkdownPreview content={activeTab.content} />
        ) : (
          <Editor
            height="100%"
            theme={editorTheme}
            path={activeTab.path}
            language={activeTab.language}
            value={activeTab.content}
            options={{
              readOnly: true,
              minimap: { enabled: true },
              fontSize: 13,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              scrollBeyondLastLine: false,
              automaticLayout: true,
              padding: { top: 8 },
            }}
          />
        )}
      </div>
    </div>
  );
}
