/**
 * Wrap consecutive ASCII / box-drawing diagram lines in a fenced code block
 * so markdown does not flatten them into wrapped paragraphs.
 *
 * Skips content already inside ``` fences.
 */

// Box-drawing only — do NOT include → arrows (those appear in normal markdown lists).
const BOX_CHARS =
  /[┌┐└┘├┤┬┴┼─│╭╮╯╰┏┓┗┛┣┫┳┻╋━┃╔╗╚╝╠╣╦╩╬═║]/

const OLD_SCHOOL_BOX = /(?:^\s*[+|].*[+|]\s*$)|(?:^\s*[+|]-+[+|]\s*$)/;

function isDiagramLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  // Never treat markdown list / heading lines as ASCII art.
  if (/^([-*+]|\d+\.)\s+/.test(trimmed) || /^#{1,6}\s/.test(trimmed)) return false;
  if (/^\*\*[^*]+\*\*/.test(trimmed)) return false;
  if (BOX_CHARS.test(line)) return true;
  // Classic ASCII boxes: +----+ | text |
  if (OLD_SCHOOL_BOX.test(line)) return true;
  // Continuation of a diagram: mostly pipes / dashes with short labels
  if (/^[|+\-\\/ ]{4,}$/.test(trimmed)) return true;
  if ((trimmed.match(/\|/g) || []).length >= 2 && trimmed.length >= 8 && !trimmed.includes("→")) {
    return true;
  }
  return false;
}

function isFence(line: string): boolean {
  return /^(`{3,}|~{3,})/.test(line.trimStart());
}

/**
 * If a run of diagram-looking lines appears outside a code fence, wrap it in
 * ```ascii so MarkdownView can render a monospace diagram panel.
 */
export function preserveAsciiDiagrams(markdown: string): string {
  if (!markdown) return markdown;
  // Fast path: no obvious diagram characters
  if (!BOX_CHARS.test(markdown) && !markdown.includes("+--") && !/\n\s*\|.+\|\s*\n/.test(markdown)) {
    return markdown;
  }

  const lines = markdown.split("\n");
  const out: string[] = [];
  let inFence = false;
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (isFence(line)) {
      inFence = !inFence;
      out.push(line);
      i += 1;
      continue;
    }

    if (inFence) {
      out.push(line);
      i += 1;
      continue;
    }

    if (isDiagramLine(line)) {
      const block: string[] = [];
      // Include a blank line only if sandwiched inside the diagram later.
      while (i < lines.length) {
        const cur = lines[i];
        if (isFence(cur)) break;
        if (isDiagramLine(cur)) {
          block.push(cur);
          i += 1;
          continue;
        }
        // Allow a single blank line between diagram rows (rare); peek ahead.
        if (!cur.trim() && i + 1 < lines.length && isDiagramLine(lines[i + 1])) {
          block.push(cur);
          i += 1;
          continue;
        }
        break;
      }

      if (block.filter((l) => l.trim()).length >= 3) {
        out.push("```ascii");
        out.push(...block);
        out.push("```");
      } else {
        out.push(...block);
      }
      continue;
    }

    out.push(line);
    i += 1;
  }

  return out.join("\n");
}
