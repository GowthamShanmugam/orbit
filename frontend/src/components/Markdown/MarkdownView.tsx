import AsciiDiagramBlock from "@/components/Markdown/AsciiDiagramBlock";
import {
  enhanceStateMachines,
  formatStateMachine,
  looksLikeStateMachine,
} from "@/components/Markdown/enhanceStateMachines";
import MermaidBlock from "@/components/Markdown/MermaidBlock";
import { preserveAsciiDiagrams } from "@/components/Markdown/preserveAsciiDiagrams";
import type { Components } from "react-markdown";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { useMemo } from "react";

type Variant = "chat" | "doc";

type Props = {
  content: string;
  /** chat = compact assistant bubbles; doc = editor markdown preview */
  variant?: Variant;
  className?: string;
  /** Turn single newlines into line breaks (useful for review comments). */
  breaks?: boolean;
};

const ASCII_LANGS = new Set(["ascii", "text", "diagram", "art", "box"]);

function codeComponent(variant: Variant): Components["code"] {
  return ({ className, children }) => {
    const raw = String(children).replace(/\n$/, "");
    // Bare fences (``` … ```) have no language-* class; still treat multiline as a block.
    const isBlock = Boolean(className?.includes("language-")) || raw.includes("\n");
    // Unfenced multi-line code from some parsers — treat box art as a diagram.
    if (!isBlock && raw.includes("\n") && /[┌│└┘├─┐]/.test(raw)) {
      return <AsciiDiagramBlock chart={raw} density={variant === "doc" ? "doc" : "chat"} />;
    }
    if (!isBlock) {
      return (
        <code
          className={
            variant === "doc"
              ? "rounded-md bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[12px] text-[var(--o-accent)]"
              : "rounded-md bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[11px] text-[var(--o-accent)]"
          }
        >
          {children}
        </code>
      );
    }

    const lang = (className?.replace("language-", "") ?? "").trim().toLowerCase();

    if (lang === "mermaid") {
      return <MermaidBlock chart={raw} density={variant === "doc" ? "doc" : "chat"} />;
    }

    // AI often dumps state machines into a plain code fence — upgrade in place.
    if (looksLikeStateMachine(raw)) {
      const upgraded = formatStateMachine(raw);
      if (upgraded) {
        return (
          <MarkdownView content={upgraded} variant={variant} className="my-2 space-y-2" />
        );
      }
    }

    if (ASCII_LANGS.has(lang) || /[┌│└┘├─┐╔╚]/.test(raw)) {
      return <AsciiDiagramBlock chart={raw} density={variant === "doc" ? "doc" : "chat"} />;
    }

    return (
      <div className={variant === "doc" ? "group relative my-3" : "group relative my-2"}>
        {lang && (
          <span className="absolute right-2.5 top-2 rounded bg-[var(--o-bg-subtle)] px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-[var(--o-text-tertiary)]">
            {lang}
          </span>
        )}
        <pre
          className={
            variant === "doc"
              ? "overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-4 font-mono text-[12px] leading-relaxed text-[var(--o-text)]"
              : "overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] p-3 font-mono text-[11px] leading-relaxed text-[var(--o-text)]"
          }
        >
          <code>{raw}</code>
        </pre>
      </div>
    );
  };
}

function chatComponents(): Components {
  return {
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
    code: codeComponent("chat"),
    pre: ({ children }) => <>{children}</>,
    table: ({ children }) => (
      <div className="my-2 overflow-x-auto rounded-lg border border-[var(--o-border)]">
        <table className="w-full border-collapse text-[12px]">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="border-b border-[var(--o-border)] bg-[var(--o-bg-raised)]">{children}</thead>
    ),
    tbody: ({ children }) => <tbody>{children}</tbody>,
    tr: ({ children }) => <tr className="border-b border-[var(--o-border)]/50">{children}</tr>,
    th: ({ children }) => (
      <th className="px-3 py-2 text-left font-semibold text-[var(--o-text)]">{children}</th>
    ),
    td: ({ children }) => (
      <td className="px-3 py-2 text-[var(--o-text-secondary)]">{children}</td>
    ),
  };
}

function docComponents(): Components {
  return {
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
    ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-6">{children}</ul>,
    ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-6">{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    hr: () => <hr className="my-4 border-[var(--o-border)]" />,
    blockquote: ({ children }) => (
      <blockquote className="my-3 border-l-3 border-[var(--o-accent)]/30 pl-4 text-[var(--o-text-secondary)]">
        {children}
      </blockquote>
    ),
    code: codeComponent("doc"),
    pre: ({ children }) => <>{children}</>,
    table: ({ children }) => (
      <div className="my-3 overflow-x-auto rounded-lg border border-[var(--o-border)]">
        <table className="w-full border-collapse text-[13px]">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="border-b border-[var(--o-border)] bg-[var(--o-bg-raised)]">{children}</thead>
    ),
    tbody: ({ children }) => <tbody>{children}</tbody>,
    tr: ({ children }) => <tr className="border-b border-[var(--o-border)]/50">{children}</tr>,
    th: ({ children }) => (
      <th className="px-3 py-2 text-left font-semibold text-[var(--o-text)]">{children}</th>
    ),
    td: ({ children }) => (
      <td className="px-3 py-2 text-[var(--o-text-secondary)]">{children}</td>
    ),
    img: ({ src, alt }) => (
      <img src={src} alt={alt ?? ""} className="my-3 max-w-full rounded-lg" />
    ),
  };
}

export default function MarkdownView({
  content,
  variant = "chat",
  className,
  breaks = false,
}: Props) {
  const components = variant === "doc" ? docComponents() : chatComponents();
  const rendered = useMemo(
    () => preserveAsciiDiagrams(enhanceStateMachines(content)),
    [content],
  );
  const plugins = useMemo(
    () => (breaks ? [remarkGfm, remarkBreaks] : [remarkGfm]),
    [breaks],
  );
  const shell =
    className ??
    (variant === "doc"
      ? "space-y-2 text-[14px] leading-relaxed text-[var(--o-text)]"
      : "space-y-1 break-words text-[13px] leading-relaxed text-[var(--o-text)]");

  return (
    <div className={shell}>
      <Markdown remarkPlugins={plugins} components={components}>
        {rendered}
      </Markdown>
    </div>
  );
}
