import { useEffect, useId, useRef, useState } from "react";

type Props = {
  chart: string;
  /** Compact styling for chat; roomier for editor preview. */
  density?: "chat" | "doc";
};

let mermaidReady: Promise<typeof import("mermaid")> | null = null;

function loadMermaid() {
  if (!mermaidReady) {
    mermaidReady = import("mermaid").then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "neutral",
        fontFamily: "inherit",
      });
      return mod;
    });
  }
  return mermaidReady;
}

export default function MermaidBlock({ chart, density = "chat" }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const reactId = useId().replace(/:/g, "");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const source = chart.trim();
    if (!source) {
      setPending(false);
      setError(null);
      if (hostRef.current) hostRef.current.innerHTML = "";
      return;
    }

    setPending(true);
    setError(null);

    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const mod = await loadMermaid();
          // Unique id per render — mermaid requires a DOM-safe id.
          const renderId = `orbit-mermaid-${reactId}-${Math.random().toString(36).slice(2, 9)}`;
          const { svg } = await mod.default.render(renderId, source);
          if (cancelled) return;
          if (hostRef.current) hostRef.current.innerHTML = svg;
          setPending(false);
        } catch (err) {
          if (cancelled) return;
          // Incomplete diagrams while streaming often fail — show source quietly.
          setError(err instanceof Error ? err.message : "Failed to render diagram");
          setPending(false);
          if (hostRef.current) hostRef.current.innerHTML = "";
        }
      })();
    }, 120);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [chart, reactId]);

  const pad = density === "doc" ? "p-4" : "p-3";

  if (error) {
    return (
      <div
        className={`my-2 overflow-hidden rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] ${pad}`}
      >
        <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-[var(--o-text-tertiary)]">
          Mermaid (not rendered)
        </p>
        <pre className="overflow-x-auto whitespace-pre-wrap text-[11px] leading-relaxed text-[var(--o-text-secondary)]">
          {chart}
        </pre>
      </div>
    );
  }

  return (
    <div
      className={`my-2 overflow-x-auto rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] ${pad}`}
    >
      {pending && (
        <p className="mb-2 text-[10px] text-[var(--o-text-tertiary)]">Rendering diagram…</p>
      )}
      <div
        ref={hostRef}
        className="flex justify-center [&_svg]:max-w-full"
        aria-label="Mermaid diagram"
      />
    </div>
  );
}
