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
    "Use the k8s_* tools to query cluster state, fetch logs, run diagnostics, or execute tests. "
    "Only fetch what you need — do NOT dump all resources at once.\n\n"
    "IMPORTANT RULES for cluster interaction:\n"
    "1. PREFER read-only tools (k8s_get_resources, k8s_get_logs, k8s_get_events, k8s_get_namespaces, "
    "k8s_list_crds) over k8s_run_command. These are faster and don't require image pulls.\n"
    "2. Only use k8s_run_command when the read-only tools truly cannot answer the question.\n"
    "3. NEVER use Docker Hub images (bitnami/*, docker.io/*) — most clusters cannot pull from Docker Hub. "
    "Use registry.access.redhat.com/ubi9/ubi-minimal:latest for general commands, or ask the user for "
    "a suitable image if you need specific tools (e.g. a test runner image).\n"
    "4. For context clusters (read-only), you can only query resources and logs.\n"
    "5. For test clusters (read-write), you can also apply manifests, run commands, and delete resources.\n"
    "6. When the user asks to 'run tests' or 'run e2e', PREFER using local_run_command (which runs "
    "on the server with full toolchains like Go, Python, Make) over k8s_run_command. The local tool "
    "automatically injects KUBECONFIG for cluster access."
)

LOCAL_TOOLS = (
    "\n\nYou have access to local_run_command which runs shell commands on the server "
    "inside cloned repository directories. This is your primary tool for building code, "
    "running tests (e2e, unit, integration), executing Makefiles, and any task that needs "
    "the repo source code plus a connection to a cluster.\n"
    "The KUBECONFIG is automatically injected so kubectl, oc, go test, and make commands "
    "can reach the attached cluster. Use this instead of k8s_run_command for test execution.\n"
    "Steps for running tests:\n"
    "1. Use repo_list_sources to find the repo\n"
    "2. Use repo_get_file_tree or repo_search_code to find test targets (Makefile, test scripts)\n"
    "3. Use local_run_command to execute the tests\n"
    "Example: local_run_command(repo_name='opendatahub-operator', command='make e2e-test')"
)

ARTIFACT_TOOLS = (
    "\n\n## Session documents (required for reports and exports)\n"
    "You have artifact_* tools for this chat session only. "
    "They read and write files under a dedicated session folder (not the git repos). "
    "Whenever the user asks for a report, document, summary export, or any deliverable "
    "they should keep or download, you MUST use artifact_write_file to save it "
    "(e.g. under `reports/` or `docs/`). Do not only paste long deliverables in chat — "
    'persist them so they appear in the Explorer under "Session documents". '
    "Use artifact_list_directory and artifact_read_file to inspect what already exists."
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
