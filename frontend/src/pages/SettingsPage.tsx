import { requestProductTourReplay } from "@/lib/productTour";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-lg p-8">
      <h1 className="text-xl font-semibold text-[var(--o-text)]">Settings</h1>
      <p className="mt-4 text-sm leading-relaxed text-[var(--o-text-secondary)]">
        Preferences live in the top bar and sidebar. Nothing else is required here.
      </p>
      <div className="mt-8 border-t border-[var(--o-border)] pt-6">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--o-text-tertiary)]">
          Welcome tour
        </h2>
        <p className="mt-2 text-sm text-[var(--o-text-secondary)]">
          Replay the short introduction to the workspace layout and context.
        </p>
        <button
          type="button"
          onClick={() => requestProductTourReplay()}
          className="o-btn-ghost mt-3 rounded-lg border border-[var(--o-border)] px-4 py-2 text-sm"
        >
          Show welcome tour
        </button>
      </div>
    </div>
  );
}
