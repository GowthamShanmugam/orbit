/** Shared labels and copy for global and project runtime limit UIs. */

export const RUNTIME_KEYS = [
  "AI_MAX_TOOL_ROUNDS",
  "AI_CONTEXT_ASSEMBLY_MAX_TOKENS",
  "AI_MAX_CONTINUATIONS",
  "AI_TOOL_SSE_HEARTBEAT_SEC",
  "MCP_TOOL_CALL_TIMEOUT_SEC",
  "MCP_CONNECTION_TIMEOUT_SEC",
  "LOCAL_TOOL_DEFAULT_TIMEOUT_SEC",
  "LOCAL_TOOL_MAX_TIMEOUT_SEC",
] as const;

export type RuntimeLimitKey = (typeof RUNTIME_KEYS)[number];

export const RUNTIME_LABELS: Record<RuntimeLimitKey, string> = {
  AI_MAX_TOOL_ROUNDS: "Max tool rounds (agent loop)",
  AI_CONTEXT_ASSEMBLY_MAX_TOKENS: "Context assembly max tokens",
  AI_MAX_CONTINUATIONS: "Max continuations on max_tokens",
  AI_TOOL_SSE_HEARTBEAT_SEC: "SSE heartbeat interval (seconds)",
  MCP_TOOL_CALL_TIMEOUT_SEC: "MCP tool call timeout (seconds)",
  MCP_CONNECTION_TIMEOUT_SEC: "MCP connection timeout (seconds)",
  LOCAL_TOOL_DEFAULT_TIMEOUT_SEC: "Local command default timeout (seconds)",
  LOCAL_TOOL_MAX_TIMEOUT_SEC: "Local command max timeout (seconds)",
};

export const RUNTIME_PARAM_EXPLANATIONS: Record<RuntimeLimitKey, string> = {
  AI_MAX_TOOL_ROUNDS:
    "How many tool rounds are allowed per chat turn (model asks for tools → they run → model replies). The system prompt tells the model this number so it can budget tools and wrap up in plain text before the cap. When the limit is hit, Orbit still adds a plain-text recovery step instead of running more tools.",
  AI_CONTEXT_ASSEMBLY_MAX_TOKENS:
    "Upper bound on tokens when building the prompt from your session, context packs, and tools. Affects how much background fits in one request.",
  AI_MAX_CONTINUATIONS:
    "If the model hits its output token limit mid-answer, Orbit can request short follow-up completions. This limits how many of those chained completions run.",
  AI_TOOL_SSE_HEARTBEAT_SEC:
    "While tools run, the chat stream sends occasional keep-alive chunks so proxies and browsers do not time out idle connections.",
  MCP_TOOL_CALL_TIMEOUT_SEC:
    "How long to wait for a single MCP (Jira, GitHub App, etc.) tool invocation to finish before treating it as failed.",
  MCP_CONNECTION_TIMEOUT_SEC:
    "Time limit for connecting to an MCP server and for listing tools during setup and refresh.",
  LOCAL_TOOL_DEFAULT_TIMEOUT_SEC:
    "Default max runtime in seconds for shell commands the AI runs inside a cloned repo when no per-command timeout is given.",
  LOCAL_TOOL_MAX_TIMEOUT_SEC:
    "Ceiling for any local command timeout the model requests; higher values allow long builds or tests but tie up workers longer.",
};
