import {
  isProductTourCompleted,
  markProductTourCompleted,
  PRODUCT_TOUR_REPLAY_EVENT,
} from "@/lib/productTour";
import { ChevronLeft, ChevronRight, Sparkles, X } from "lucide-react";
import { Fragment, useCallback, useEffect, useState } from "react";
import { useMatch } from "react-router-dom";

type TourBlock = { type: "p"; text: string } | { type: "ul"; items: string[] };

const STEPS: { title: string; blocks: TourBlock[] }[] = [
  {
    title: "Welcome to Orbit",
    blocks: [
      {
        type: "p",
        text: "Orbit is an AI-powered developer workspace. Each project groups context sources, skills, and clusters together so the AI assistant reasons about your real code and team conventions.",
      },
      {
        type: "p",
        text: "All sessions inside a project share the same context. Need a different topic or codebase? Create a new project. Need multiple conversations within the same codebase? Create multiple sessions.",
      },
    ],
  },
  {
    title: "Sidebar navigation",
    blocks: [
      {
        type: "ul",
        items: [
          "Projects \u2014 Create and manage projects. Each project has sessions, context sources, skills, clusters, sharing, and settings.",
          "Integrations \u2014 Connect external services like GitHub, Jira, Confluence, and Google Drive. These connections power your context sources and tools.",
          "Skills \u2014 Browse and install skill packs (built-in or custom). Skills guide the AI with structured steps and can be selected in chat.",
          "Secrets \u2014 Your personal encrypted vault for API keys and credentials. Secrets are user-scoped and never shared with others.",
          "Settings \u2014 Server-wide limits, preferences, and replay this welcome tour.",
        ],
      },
      {
        type: "p",
        text: "Collapse the sidebar with the chevron icon, or drag the right edge to resize.",
      },
    ],
  },
  {
    title: "Top bar and account",
    blocks: [
      {
        type: "ul",
        items: [
          "ORBIT logo \u2014 Returns to the projects list.",
          "Breadcrumbs \u2014 Shows your current location: project name, then session title when inside a session.",
          "Model badge \u2014 In a session, shows which Claude model the chat uses.",
          "Theme toggle \u2014 Switch between light and dark mode.",
          "Account menu \u2014 Your profile and logout.",
        ],
      },
    ],
  },
  {
    title: "Inside a project",
    blocks: [
      {
        type: "p",
        text: "Open a project to see its tabs:",
      },
      {
        type: "ul",
        items: [
          "Sessions \u2014 Each session is a separate AI conversation sharing this project\u2019s context. Create one by choosing a title and model.",
          "Context Sources \u2014 Add GitHub repos, Jira boards, Confluence spaces, Google Docs, and more. Every session in the project sees these sources.",
          "Skills \u2014 Install skill packs from the catalog to guide the AI with structured workflows.",
          "Clusters \u2014 Live compute endpoints for this project. Skills and tools can use these clusters.",
          "Sharing \u2014 Invite collaborators. Shared users get access to sources, skills, clusters, and sessions.",
          "Settings \u2014 Runtime limits for this project, stacked on top of server-wide limits.",
        ],
      },
    ],
  },
  {
    title: "Session view: Explorer, Context, and Chat",
    blocks: [
      {
        type: "p",
        text: "Opening a session fills the screen with three areas:",
      },
      {
        type: "ul",
        items: [
          "Left panel \u2014 Two tabs: Explorer (file tree from cloned repos, click to open files) and Context (manage sources and session layers).",
          "Center \u2014 Multi-tab editor for viewing files from your repos.",
          "Right \u2014 Chat with the AI. Select a skill before sending to guide the conversation.",
        ],
      },
      {
        type: "p",
        text: "Drag the dividers between panels to resize. The URL updates as you navigate, so refreshing keeps you in the same view.",
      },
    ],
  },
  {
    title: "Context Sources and Session Layers",
    blocks: [
      {
        type: "p",
        text: "Inside a session\u2019s Context tab, there are two sections:",
      },
      {
        type: "ul",
        items: [
          "Context Sources \u2014 Shared across all sessions in the project. Repos, documents, and integrations added here are available to every session.",
          "Session Layers \u2014 Extra context for this session only: pull requests, tickets, docs, or pins. These don\u2019t affect other sessions.",
        ],
      },
      {
        type: "p",
        text: "Click a pull request in Session Layers to open a GitHub-style diff viewer where you can review changes, add inline comments, start reviews, and approve PRs directly from Orbit.",
      },
    ],
  },
  {
    title: "Staying safe",
    blocks: [
      {
        type: "p",
        text: "Secrets belong in the vault, not in chat messages. Orbit encrypts all vault entries and scopes them to your account only.",
      },
      {
        type: "p",
        text: "All write operations (posting comments, approving PRs, modifying resources) require your explicit confirmation. The AI will not take actions on your behalf without asking first.",
      },
      {
        type: "p",
        text: "You can replay this tour anytime from the Settings page.",
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
            Quick tour &middot; {step + 1} / {STEPS.length}
          </p>
          <h2
            id="product-tour-title"
            className="mt-1 text-lg font-semibold tracking-tight text-[var(--o-text)]"
          >
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
