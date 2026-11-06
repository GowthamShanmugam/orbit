/**
 * Detect prose "States: / Transitions:" blocks (often smashed onto one line,
 * sometimes inside a plain code fence) and rewrite as Mermaid + clean lists.
 */

const STATE_DEF =
  /\b([A-Z][A-Z0-9_]+)\s*(?:--|—|–|-)\s*([^]+?)(?=\s+[A-Z][A-Z0-9_]+\s*(?:--|—|–|-)|$)/g;
const TRANSITION_LINE =
  /([A-Z*][A-Z0-9_*]*)\s*(?:→|->|=>)\s*([A-Z*][A-Z0-9_*]*)(?:\s*\(([^)]*)\))?/g;

type Parsed = {
  states: Array<{ id: string; note: string }>;
  transitions: Array<{ from: string; to: string; label: string }>;
};

function parseStates(blob: string): Array<{ id: string; note: string }> {
  const states: Array<{ id: string; note: string }> = [];
  const seen = new Set<string>();
  let m: RegExpExecArray | null;
  const re = new RegExp(STATE_DEF.source, "g");
  while ((m = re.exec(blob)) !== null) {
    const id = m[1];
    const note = m[2].replace(/\s+/g, " ").trim();
    if (seen.has(id)) continue;
    seen.add(id);
    states.push({ id, note });
  }
  return states;
}

function parseTransitions(blob: string): Array<{ from: string; to: string; label: string }> {
  const out: Array<{ from: string; to: string; label: string }> = [];
  const seen = new Set<string>();
  let m: RegExpExecArray | null;
  const re = new RegExp(TRANSITION_LINE.source, "g");
  while ((m = re.exec(blob)) !== null) {
    const from = m[1];
    const to = m[2];
    const label = (m[3] || "").replace(/\s+/g, " ").trim();
    if (!/^[A-Z][A-Z0-9_]*$/.test(from) || !/^[A-Z][A-Z0-9_]*$/.test(to)) continue;
    const key = `${from}->${to}:${label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ from, to, label });
  }
  return out;
}

function splitStatesAndTransitions(
  raw: string,
): { statesBlob: string; transitionsBlob: string } | null {
  const m = raw.match(/states\s*:\s*([\s\S]*?)\s*transitions\s*:\s*([\s\S]*)/i);
  if (!m) return null;
  return { statesBlob: m[1].trim(), transitionsBlob: m[2].trim() };
}

function parseMachine(raw: string): Parsed | null {
  const split = splitStatesAndTransitions(raw);
  if (!split) return null;
  const states = parseStates(split.statesBlob);
  const transitions = parseTransitions(split.transitionsBlob);
  if (states.length < 3 || transitions.length < 1) return null;
  return { states, transitions };
}

function toMermaid(parsed: Parsed): string {
  const lines = ["stateDiagram-v2"];
  for (const s of parsed.states) {
    const short = s.note.length > 60 ? `${s.note.slice(0, 57)}...` : s.note;
    // Parentheses break Mermaid labels — strip them.
    const safe = short.replace(/[()#:[\]]/g, " ").replace(/\s+/g, " ").trim();
    lines.push(`    ${s.id} : ${safe}`);
  }
  for (const t of parsed.transitions) {
    if (t.label) {
      const safe = t.label.replace(/[()#:[\]]/g, " ").replace(/\s+/g, " ").trim();
      lines.push(`    ${t.from} --> ${t.to} : ${safe}`);
    } else {
      lines.push(`    ${t.from} --> ${t.to}`);
    }
  }
  return lines.join("\n");
}

function toMarkdownLists(parsed: Parsed): string {
  const stateLines = parsed.states.map((s) => `- **${s.id}** — ${s.note}`);
  const transLines = parsed.transitions.map((t) =>
    t.label ? `- **${t.from}** → **${t.to}** (${t.label})` : `- **${t.from}** → **${t.to}**`,
  );
  return ["**States**", ...stateLines, "", "**Transitions**", ...transLines].join("\n");
}

export function formatStateMachine(raw: string): string | null {
  const parsed = parseMachine(raw);
  if (!parsed) return null;
  return ["```mermaid", toMermaid(parsed), "```", "", toMarkdownLists(parsed)].join("\n");
}

/**
 * True when a code-block body looks like a smashed States/Transitions machine.
 */
export function looksLikeStateMachine(text: string): boolean {
  return /states\s*:/i.test(text) && /transitions\s*:/i.test(text) && /(?:→|->)/.test(text);
}

function findRangesOutsideFences(text: string): Array<{ start: number; end: number }> {
  const ranges: Array<{ start: number; end: number }> = [];
  const lower = text.toLowerCase();
  let searchFrom = 0;

  while (searchFrom < text.length) {
    const statesIdx = lower.indexOf("states:", searchFrom);
    if (statesIdx < 0) break;

    const before = text.slice(0, statesIdx);
    const fenceCount = (before.match(/^```/gm) || []).length;
    if (fenceCount % 2 === 1) {
      searchFrom = statesIdx + 7;
      continue;
    }

    const afterStates = text.slice(statesIdx);
    const transitionsRel = afterStates.toLowerCase().indexOf("transitions:");
    if (transitionsRel < 0) {
      searchFrom = statesIdx + 7;
      continue;
    }

    let bodyEnd = text.length;
    const afterTrans = text.slice(statesIdx + transitionsRel + "transitions:".length);
    const endCandidates = [
      afterTrans.search(/\n#{1,6}\s/),
      afterTrans.search(/\n```/),
      afterTrans.search(/\n\n\n/),
    ].filter((n) => n >= 0);
    if (endCandidates.length) {
      bodyEnd = statesIdx + transitionsRel + "transitions:".length + Math.min(...endCandidates);
    }

    const raw = text.slice(statesIdx, bodyEnd);
    if (parseMachine(raw)) {
      ranges.push({ start: statesIdx, end: bodyEnd });
      searchFrom = bodyEnd;
    } else {
      searchFrom = statesIdx + 7;
    }
  }
  return ranges;
}

/**
 * Also upgrade whole fenced ``` / ```text / ```ascii blocks that contain a machine.
 */
function upgradeFencedMachines(markdown: string): string {
  return markdown.replace(/```([^\n`]*)\n([\s\S]*?)```/g, (full, lang: string, body: string) => {
    const l = (lang || "").trim().toLowerCase();
    if (l === "mermaid") return full;
    if (!looksLikeStateMachine(body)) return full;
    const formatted = formatStateMachine(body.trim());
    return formatted ?? full;
  });
}

export function enhanceStateMachines(markdown: string): string {
  if (!markdown) return markdown;
  if (!/states\s*:/i.test(markdown) || !/transitions\s*:/i.test(markdown)) {
    return markdown;
  }

  // 1) Upgrade machines trapped inside plain code fences.
  let result = upgradeFencedMachines(markdown);

  // 2) Upgrade machines in normal prose.
  const ranges = findRangesOutsideFences(result);
  for (let i = ranges.length - 1; i >= 0; i -= 1) {
    const range = ranges[i];
    const raw = result.slice(range.start, range.end);
    const formatted = formatStateMachine(raw.trim());
    if (!formatted) continue;
    result = result.slice(0, range.start) + formatted + result.slice(range.end);
  }

  return result;
}
