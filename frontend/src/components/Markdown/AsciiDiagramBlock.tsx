type Props = {
  chart: string;
  density?: "chat" | "doc";
};

export default function AsciiDiagramBlock({ chart, density = "chat" }: Props) {
  const pad = density === "doc" ? "p-4" : "p-3";
  const text = density === "doc" ? "text-[12px]" : "text-[10px]";

  return (
    <div
      className={`my-2 overflow-x-auto rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] ${pad}`}
    >
      <p className="mb-2 text-[9px] font-medium uppercase tracking-wide text-[var(--o-text-tertiary)]">
        Flow diagram
      </p>
      <pre
        className={`m-0 overflow-x-auto whitespace-pre font-mono ${text} leading-snug text-[var(--o-text)]`}
      >
        {chart}
      </pre>
    </div>
  );
}
