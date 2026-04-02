import {
  isProductTourCompleted,
  markProductTourCompleted,
  PRODUCT_TOUR_REPLAY_EVENT,
} from "@/lib/productTour";
import { ChevronLeft, ChevronRight, Sparkles, X } from "lucide-react";
import { Fragment, useCallback, useEffect, useState } from "react";
import { useMatch } from "react-router-dom";

/** One paragraph or a bulleted list for readable layout (no raw bullet character in one paragraph). */
type TourBlock =
  | { type: "p"; text: string }
  | { type: "ul"; items: string[] };

const STEPS: { title: string; blocks: TourBlock[] }[] = [
  {
    title: "Welcome to Orbit",
    blocks: [
      {
        type: "p",
        text: "Orbit is a context-first IDE: your projects carry repositories, documents, secrets, and tool connections so the assistant reasons about real code and team conventions—not a blank chat.",
      },
      {
        type: "p",
        text: "Work happens in projects: you attach context packs, open coding sessions, and keep each workspace’s knowledge separate. Nothing here replaces reading your own diff or reviewing security-sensitive changes; it gives you a structured place to collaborate with AI.",
      },
    ],
  },
  {
    title: "Sidebar: where everything lives",
    blocks: [
      {
        type: "ul",
        items: [
          "Projects — Create and open projects, then drill into sessions, sharing, and project settings.",
          "Context Hub — Browse and install context packs (bundles of repos, docs, and patterns) you can attach to projects.",
          "Skills — Connect and toggle MCP integrations (e.g. GitHub, Jira): enable, test connection, and refresh tools so the model can call them when allowed.",
          "Workflows — Built-in and custom prompt patterns; pick one in chat before sending when you want structured steps.",
          "Secrets — Encrypted vault: browse all projects’ secrets from here, or open a project’s Secrets tab for that project only.",
          "Settings — Replay this welcome tour anytime.",
        ],
      },
      {
        type: "p",
        text: "Use the chevron at the top of the bar to collapse to icons-only mode. Drag the narrow strip on the bar’s right edge to resize (about 200–400px).",
      },
    ],
  },
  {
    title: "Top bar: navigation and account",
    blocks: [
      {
        type: "ul",
        items: [
          "ORBIT — Jumps back to the projects list.",
          "Breadcrumbs — “Dashboard” when no project is open; then project name (click to return to the project page); in a session you also see the session title.",
          "Model badge — In an open session, shows which Claude model this chat uses (chosen when the session was created).",
          "About — UI version and a link to the source repository.",
          "Sun/Moon — Toggle light or dark theme (saved for this browser).",
          "Person icon — Account menu with your name or email and Logout.",
        ],
      },
    ],
  },
  {
    title: "Project page: tabs and permissions",
    blocks: [
      {
        type: "p",
        text: "Open a project from Projects. Along the top you’ll find:",
      },
      {
        type: "ul",
        items: [
          "Sessions — List and create sessions: each session is a separate IDE + chat with its own history. Creating a session asks for a title and model.",
          "Context Hub — Install or remove context packs for this project only.",
          "Clusters — Live clusters for this project (context vs test roles): add, test, and manage endpoints your workflows may use.",
          "Secrets — Project-scoped vault entries.",
          "Sharing — Invite collaborators and set access.",
          "Settings — Project-level settings.",
        ],
      },
      {
        type: "p",
        text: "If you have access, you’ll see Edit (name/description) and Delete project. Shared projects may be read-only in the session IDE—editing and destructive actions will be disabled.",
      },
    ],
  },
  {
    title: "Session IDE: Explorer, editor, chat",
    blocks: [
      {
        type: "p",
        text: "Opening a session fills the screen: the main sidebar is hidden so you have maximum room.",
      },
      {
        type: "p",
        text: "Left strip: two tabs — Explorer shows cloned repositories as a file tree (open files in the editor). Context opens the same context manager as on the project page, but scoped to this session.",
      },
      {
        type: "p",
        text: "Center: multi-tab editor for files from your repos. Right: chat with the model for this session.",
      },
      {
        type: "p",
        text: "Drag the thin dividers between panels to resize; widths are remembered in the browser. The footer shows the session title, the model, and (if allowed) a trash control to delete the session permanently.",
      },
    ],
  },
  {
    title: "Context: Sources vs Layers",
    blocks: [
      {
        type: "p",
        text: "In Context, two sub-tabs:",
      },
      {
        type: "ul",
        items: [
          "Sources — Shared for the whole project: GitHub/GitLab repos, Jira, Confluence, Google Docs/Drive, pinned files, snippets, and more. Every session sees these; cloning a repo here is what fills Explorer’s file tree.",
          "Layers — Only this session: extra tickets, PRs, docs, pins, or even excerpts from past sessions merged into this chat’s prompt without changing the rest of the team’s defaults.",
        ],
      },
      {
        type: "p",
        text: "Remove items anytime (when you have write access). Repo sources may show a clone/refresh action while code is syncing.",
      },
    ],
  },
  {
    title: "Skills, workflows, and staying safe",
    blocks: [
      {
        type: "p",
        text: "Skills (sidebar) are off until you connect something—use them when you want the model to use approved external tools, not for every message.",
      },
      {
        type: "p",
        text: "Workflows define how the assistant should behave step-by-step; select one from the chat UI before you send when you want that structure.",
      },
      {
        type: "p",
        text: "Secrets belong in the vault, not in pasted prompts. The app also runs a lightweight scanner to warn about accidental secret patterns in open content—treat alerts seriously and rotate credentials if something leaked.",
      },
    ],
  },
];

function TourBody({ blocks }: { blocks: TourBlock[] }) {
  return (
    <div className="max-w-prose space-y-4 text-sm leading-relaxed text-[var(--o-text-secondary)]">
      {blocks.map((block, i) => (
        <Fragment key={i}>
          {block.type === "p" ? (
            <p className="text-pretty">{block.text}</p>
          ) : (
            <ul className="list-disc space-y-2.5 pl-5 marker:text-[var(--o-accent)]">
              {block.items.map((item, j) => (
                <li key={j} className="pl-1">
                  {item}
                </li>
              ))}
            </ul>
          )}
        </Fragment>
      ))}
    </div>
  );
}

export default function ProductTour() {
  const sessionMatch = useMatch("/projects/:id/sessions/:sessionId");
  const isSessionIde = Boolean(sessionMatch);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  /** Skip, Done, or X: do not auto-show again until user replays from Settings. */
  const dismissTour = useCallback(() => {
    markProductTourCompleted();
    setOpen(false);
  }, []);

  useEffect(() => {
    if (isSessionIde || isProductTourCompleted()) return undefined;
    const id = window.setTimeout(() => {
      setStep(0);
      setOpen(true);
    }, 500);
    return () => window.clearTimeout(id);
  }, [isSessionIde]);

  useEffect(() => {
    function onReplay() {
      setStep(0);
      setOpen(true);
    }
    window.addEventListener(PRODUCT_TOUR_REPLAY_EVENT, onReplay);
    return () => window.removeEventListener(PRODUCT_TOUR_REPLAY_EVENT, onReplay);
  }, []);

  if (!open) return null;

  const last = step === STEPS.length - 1;
  const s = STEPS[step];

  return (
    <div
      className="o-modal-backdrop fixed inset-0 z-[250] flex items-center justify-center p-4"
      role="presentation"
      onClick={dismissTour}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="product-tour-title"
        className="o-modal relative flex max-h-[min(85vh,40rem)] w-full max-w-xl flex-col shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={dismissTour}
          className="absolute right-3 top-3 z-10 rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          aria-label="Close tour"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain border-b border-[var(--o-border)] px-6 pb-5 pt-6 pr-12">
          <div className="mb-3 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <Sparkles className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
            Quick tour · {step + 1} / {STEPS.length}
          </p>
          <h2 id="product-tour-title" className="mt-1 text-lg font-semibold tracking-tight text-[var(--o-text)]">
            {s.title}
          </h2>
          <div className="mt-4">
            <TourBody blocks={s.blocks} />
          </div>
        </div>
        <div className="flex shrink-0 items-center justify-between gap-3 px-6 py-4">
          <button
            type="button"
            onClick={dismissTour}
            className="o-btn-ghost rounded-lg px-3 py-2 text-xs"
          >
            Skip
          </button>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button
                type="button"
                onClick={() => setStep((x) => x - 1)}
                className="o-btn-ghost inline-flex items-center gap-1 rounded-lg px-3 py-2 text-xs"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                Back
              </button>
            )}
            {!last ? (
              <button
                type="button"
                onClick={() => setStep((x) => x + 1)}
                className="o-btn-primary inline-flex items-center gap-1 rounded-lg px-4 py-2 text-xs"
              >
                Next
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button
                type="button"
                onClick={dismissTour}
                className="o-btn-primary rounded-lg px-4 py-2 text-xs"
              >
                Done
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
