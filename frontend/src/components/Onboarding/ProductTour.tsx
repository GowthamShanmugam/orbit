import {
  isProductTourCompleted,
  markProductTourCompleted,
  PRODUCT_TOUR_REPLAY_EVENT,
} from "@/lib/productTour";
import { ChevronLeft, ChevronRight, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useMatch } from "react-router-dom";

const STEPS: { title: string; body: string }[] = [
  {
    title: "Welcome to Orbit",
    body: `Orbit is a context-first IDE: your projects carry repositories, documents, secrets, and tool connections so the assistant reasons about real code and team conventions—not a blank chat.

Work happens in projects: you attach context packs, open coding sessions, and keep each workspace’s knowledge separate. Nothing here replaces reading your own diff or reviewing security-sensitive changes; it gives you a structured place to collaborate with AI.`,
  },
  {
    title: "Sidebar: where everything lives",
    body: `• Projects — Create and open projects, then drill into sessions, sharing, and project settings.
• Context Hub — Browse and install context packs (bundles of repos, docs, and patterns) you can attach to projects.
• Skills — Connect and toggle MCP integrations (e.g. GitHub, Jira): enable, test connection, and refresh tools so the model can call them when allowed.
• Workflows — Built-in and custom prompt patterns; you’ll pick one in chat before sending messages when you want structured steps.
• Secrets — Encrypted vault: browse all projects’ secrets from here, or open a project’s Secrets tab for that project only.
• Settings — Replay this welcome tour anytime.

Use the chevron at the top of the bar to collapse icons-only mode. Drag the narrow strip on the bar’s right edge to resize (about 200–400px).`,
  },
  {
    title: "Top bar: navigation and account",
    body: `• ORBIT — Jumps back to the projects list.
• Breadcrumbs — “Dashboard” when no project is open; then project name (click to return to the project page); in a session you also see the session title.
• Model badge — In an open session, shows which Claude model this chat uses (chosen when the session was created).
• About — UI version and a link to the source repository.
• Sun/Moon — Toggle light or dark theme (saved for this browser).
• Person icon — Account menu with your name or email and Logout.`,
  },
  {
    title: "Project page: tabs and permissions",
    body: `Open a project from Projects. Along the top you’ll find:

• Sessions — List and create sessions: each session is a separate IDE + chat with its own history. Creating a session asks for a title and model.
• Context Hub — Install or remove context packs for this project only.
• Clusters — Live clusters for this project (context vs test roles): add, test, and manage endpoints your workflows may use.
• Secrets — Project-scoped vault entries.
• Sharing — Invite collaborators and set access.
• Settings — Project-level settings.

If you have access, you’ll see Edit (name/description) and Delete project. Shared projects may be read-only in the session IDE—editing and destructive actions will be disabled.`,
  },
  {
    title: "Session IDE: Explorer, editor, chat",
    body: `Opening a session fills the screen: the main sidebar is hidden so you have maximum room.

Left strip: two tabs — Explorer shows cloned repositories as a file tree (open files in the editor). Context opens the same context manager as on the project page, but scoped to this session.

Center: multi-tab editor for files from your repos.

Right: chat with the model for this session.

Drag the thin dividers between panels to resize; widths are remembered in the browser. The footer shows the session title, the model, and (if allowed) a trash control to delete the session permanently.`,
  },
  {
    title: "Context: Sources vs Layers",
    body: `In Context, two sub-tabs:

• Sources — Shared for the whole project: GitHub/GitLab repos, Jira, Confluence, Google Docs/Drive, pinned files, snippets, and more. Every session sees these; cloning a repo here is what fills Explorer’s file tree.

• Layers — Only this session: extra tickets, PRs, docs, pins, or even excerpts from past sessions merged into this chat’s prompt without changing the rest of the team’s defaults.

Remove items anytime (when you have write access). Repo sources may show a clone/refresh action while code is syncing.`,
  },
  {
    title: "Skills, workflows, and staying safe",
    body: `Skills (sidebar) are off until you connect something—use them when you want the model to use approved external tools, not for every message.

Workflows define how the assistant should behave step-by-step; select one from the chat UI before you send when you want that structure.

Secrets belong in the vault, not in pasted prompts. The app also runs a lightweight scanner to warn about accidental secret patterns in open content—treat alerts seriously and rotate credentials if something leaked.`,
  },
];

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
        className="o-modal relative w-full max-w-lg shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={dismissTour}
          className="absolute right-3 top-3 rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          aria-label="Close tour"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="border-b border-[var(--o-border)] px-6 pb-4 pt-6 pr-12">
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <Sparkles className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
            Quick tour · {step + 1} / {STEPS.length}
          </p>
          <h2 id="product-tour-title" className="mt-1 text-lg font-semibold text-[var(--o-text)]">
            {s.title}
          </h2>
          <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-[var(--o-text-secondary)]">
            {s.body}
          </p>
        </div>
        <div className="flex items-center justify-between gap-3 px-6 py-4">
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
