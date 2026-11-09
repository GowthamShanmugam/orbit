/** Prepare MR/PR comment text so plain code keeps line breaks when rendered as markdown. */

const CODEISH =
  /^(func |def |class |package |import |SELECT |CREATE |WITH |fn |pub |async |export |const |let |var |type |interface |struct |return |if |for |while )/i;

/** Statement that can resume after a collapsed // comment (not English "for …"). */
const AFTER_COMMENT =
  /(?=\s+(?:for _,|for \w+ :=|for \w+ \w+ :=|if |return |schemas\s*:?=|roleBase\s*:?=))/;

/** Expand collapsed one-line Go/C-like snippets (newlines often lost in comments). */
function softBreakOneLineCode(s: string): string {
  let out = s;
  // Put // comments on their own line after } ; )
  out = out.replace(/([;})])\s*(\/\/)/g, "$1\n$2");
  // Collapsed paste: // would eat the rest of the line. End it before the next statement.
  out = out.replace(new RegExp(`\\/\\/(.*?)${AFTER_COMMENT.source}`, "g"), (_full, body: string) => {
    return `//${String(body).trimEnd()}\n`;
  });
  out = out.replace(/\{\s+/g, "{\n\t");
  out = out.replace(/\s+\}/g, "\n}");
  // Statement breaks only outside // comment lines (English "for …" must stay in comments).
  out = out
    .split("\n")
    .map((line) => {
      if (line.trimStart().startsWith("//")) return line;
      let next = line.replace(/;\s+(?!err\s*!=)(?=\S)/g, ";\n\t");
      next = next.replace(/([;}])\s+(?=(?:for _,|for \w+|if |return |schemas |roleBase ))/g, "$1\n");
      next = next.replace(/\)\s+(?=schemas\s)/g, ")\n");
      next = next.replace(/(\S)\s+(?=if )/g, "$1\n");
      return next;
    })
    .join("\n");
  return out;
}

function looksLikeCode(text: string, lines: string[]): boolean {
  if (CODEISH.test(text) && text.includes("{") && text.includes("}")) return true;
  if (lines.length < 2) return false;
  const hits = lines.filter(
    (line) =>
      CODEISH.test(line.trim()) ||
      /[{}]$/.test(line.trim()) ||
      /^\s{2,}\S/.test(line),
  ).length;
  return hits >= Math.ceil(lines.length / 2);
}

function fenceLang(text: string): string {
  if (
    /^func |^package |^type |^interface /m.test(text) ||
    text.includes("fmt.") ||
    text.includes(":=")
  ) {
    return "go";
  }
  if (/^SELECT |^CREATE |^WITH |^INSERT /im.test(text)) return "sql";
  if (/^def |^class |^import /m.test(text)) return "python";
  return "";
}

function fenceProseBlock(block: string): string {
  const trimmed = block.trim();
  if (!trimmed) return block;
  const lines = trimmed.split("\n");
  if (!looksLikeCode(trimmed, lines)) return block;
  const body = lines.length === 1 ? softBreakOneLineCode(trimmed) : trimmed;
  const lang = fenceLang(body);
  const lead = block.match(/^\s*/)?.[0] ?? "";
  const trail = block.match(/\s*$/)?.[0] ?? "";
  return `${lead}\`\`\`${lang}\n${body}\n\`\`\`${trail}`;
}

/** Fence unfenced code-looking blocks; leave existing fences alone. */
export function prepareCommentMarkdown(raw: string): string {
  const text = raw.replace(/\r\n/g, "\n");
  const parts = text.split(/(```[\s\S]*?```)/);
  return parts
    .map((part, index) => {
      if (index % 2 === 1) return part;
      return part
        .split(/(\n{2,})/)
        .map((chunk) => (chunk.match(/^\n+$/) ? chunk : fenceProseBlock(chunk)))
        .join("");
    })
    .join("");
}
