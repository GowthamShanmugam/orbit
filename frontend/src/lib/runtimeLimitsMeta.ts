/** Shared labels and copy for global and project runtime limit UIs. */

export const RUNTIME_KEYS = [
  "AI_MAX_TOOL_ROUNDS",
  "MCP_TOOL_CALL_TIMEOUT_SEC",
  "LOCAL_TOOL_DEFAULT_TIMEOUT_SEC",
] as const;

export type RuntimeLimitKey = (typeof RUNTIME_KEYS)[number];

export const RUNTIME_LABELS: Record<RuntimeLimitKey, string> = {
  AI_MAX_TOOL_ROUNDS: "Max tool rounds per message",
  MCP_TOOL_CALL_TIMEOUT_SEC: "Integration timeout (seconds)",
  LOCAL_TOOL_DEFAULT_TIMEOUT_SEC: "Command timeout (seconds)",
};

export const RUNTIME_PARAM_EXPLANATIONS: Record<RuntimeLimitKey, string> = {
  AI_MAX_TOOL_ROUNDS:
    "How many tool rounds the AI can use per chat message. Increase if the AI stops too early on complex tasks (e.g. reading multiple files). Decrease to get faster, shorter answers.",
  MCP_TOOL_CALL_TIMEOUT_SEC:
    "How long to wait for an integration call (Jira, GitHub, Google Drive, etc.) to finish before treating it as failed. Increase if your integrations are slow.",
  LOCAL_TOOL_DEFAULT_TIMEOUT_SEC:
    "Max time for shell commands the AI runs (builds, tests, scripts). Increase if your builds or tests take a long time.",
};
