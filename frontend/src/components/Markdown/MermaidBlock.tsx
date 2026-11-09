import { useEffect, useId, useRef, useState } from "react";

type Props = {
  chart: string;
  /** Compact styling for chat; roomier for editor preview; review keeps natural size. */
  density?: "chat" | "doc" | "review";
  /** When true, SVG keeps its natural size and the container scrolls instead of shrinking. */
  scrollable?: boolean;
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
        flowchart: {
          htmlLabels: false,
          curve: "basis",
          padding: 12,
          nodeSpacing: 36,
          rankSpacing: 40,
        },
      });
      return mod;
    });
  }
  return mermaidReady;
}

export default function MermaidBlock({ chart, density = "chat", scrollable }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const reactId = useId().replace(/:/g, "");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(true);
  const keepNaturalSize = scrollable ?? density === "review";
  const fontSize = density === "review" ? "16px" : density === "doc" ? "14px" : "13px";

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
          if (hostRef.current) {
            hostRef.current.innerHTML = svg;
            const el = hostRef.current.querySelector("svg");
            if (el) {
              el.style.maxWidth = keepNaturalSize ? "none" : "100%";
              el.style.height = "auto";
              el.style.fontSize = fontSize;
            }
          }
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
  }, [chart, reactId, keepNaturalSize, fontSize]);

  const pad = density === "chat" ? "p-3" : "p-4";

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
      className={`my-2 rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] ${pad} ${
        keepNaturalSize ? "overflow-auto" : "overflow-x-auto"
      }`}
    >
      {pending && (
        <p className="mb-2 text-[10px] text-[var(--o-text-tertiary)]">Rendering diagram…</p>
      )}
      <div
        ref={hostRef}
        className={
          keepNaturalSize
            ? "inline-block min-w-full [&_svg]:max-w-none"
            : "flex justify-center [&_svg]:max-w-full"
        }
        aria-label="Mermaid diagram"
      />
    </div>
  );
}
