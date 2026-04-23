"""Tool-specific addendums appended to the system prompt based on available capabilities."""

from __future__ import annotations

from app.services.runtime_settings import eff_int

REPO_TOOLS = (
    "\n\nYou have access to the project's code repositories via repo_* tools. "
    "Start with repo_list_sources to see available repos, then use "
    "repo_get_file_tree to understand the structure before reading specific files. "
    "Use repo_search_code to find definitions, usages, or patterns across the codebase. "
    "Only read files that are relevant to the user's question."
)

CLUSTER_TOOLS = (
    "\n\nYou have access to live Kubernetes clusters attached to this project. "
    "Only fetch what you need — do NOT dump all resources at once.\n"
    "For context clusters (read-only), you can only query resources and logs.\n"
    "For test clusters (read-write), you can also apply manifests, run commands, and delete resources.\n"
    "NEVER use Docker Hub images (bitnami/*, docker.io/*) — most clusters cannot pull from Docker Hub."
)

LOCAL_TOOLS = (
    "\n\nYou can run shell commands via local_run_command (on the server) "
    "and k8s_run_command (inside a pod on the cluster).\n"
    "- local_run_command: set repo_name when the command needs repo source code; "
    "omit it for general commands. KUBECONFIG is auto-injected.\n"
    "- k8s_run_command: use only when the command must run inside the cluster network.\n"
    "- Prefer k8s_get_*/k8s_apply_manifest for direct K8s API calls — they are faster.\n"
    "- Always add timeouts to network commands (e.g. curl --max-time 30)."
)

ARTIFACT_TOOLS = (
    "\n\n## Session documents (required for reports and exports)\n"
    "You have artifact_* tools for this chat session only. "
    "They read and write files under a dedicated session folder (not the git repos). "
    "Whenever the user asks for a report, document, summary export, or any deliverable "
    "they should keep or download, you MUST call the artifact_write_file tool to save it "
    "(e.g. under `reports/` or `docs/`). Do not only paste long deliverables in chat — "
    'persist them so they appear in the Explorer under "Session documents". '
    "Use artifact_list_directory and artifact_read_file to inspect what already exists.\n\n"
    "CRITICAL: A file is ONLY saved when you invoke the artifact_write_file tool and receive "
    "a success response. NEVER tell the user a file has been saved unless you have actually "
    "called artifact_write_file and received an {\"ok\": true} result. Saying you saved a file "
    "without calling the tool is a hallucination and the user will see an empty documents panel."
)

MCP_TOOLS = (
    "\n\nYou have access to MCP skill tools (prefixed with mcp_<skill>__). "
    "These connect to external services like Jira, GitHub, and others. "
    "Use them when you need to interact with issue trackers, create PRs, "
    "transition tickets, search for issues, etc. "
    "The tool name format is mcp_<skill>__<tool_name> -- e.g., "
    "mcp_atlassian__jira_search or mcp_github__create_pull_request.\n\n"
    "IMPORTANT tips for Jira/Atlassian searches:\n"
    "- Always include maxResults (e.g. maxResults=20) in JQL search calls to avoid timeouts.\n"
    "- Prefer reading specific issues by key (jira_get_issue) over broad searches.\n"
    "- For large backlogs, paginate: use startAt + maxResults.\n"
    "- Narrow JQL with project, status, assignee, or date filters.\n"
    "- If a search times out, retry with a more specific query."
)


def tool_round_budget() -> str:
    """Dynamic addendum telling the model its per-turn tool round cap."""
    n = max(1, eff_int("AI_MAX_TOOL_ROUNDS"))
    return (
        "\n\n## Tool-use budget (this assistant turn)\n"
        f"This turn allows at most **{n} tool-use round(s)**. Each round is: you request tools → "
        "results are returned → you may request tools again. "
        "Budget deliberately: take only the tool calls you need, avoid redundant exploration, and "
        "**move toward a clear final answer in plain text** before you run out of rounds. "
        "If the task is too large to finish within this budget, summarize progress, what remains, and "
        "what the user should do next (including continuing in a new message)."
    )
