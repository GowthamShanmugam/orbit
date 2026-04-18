import { apiClient } from "./client";

export interface PRListItem {
  number: number;
  title: string;
  state: string;
  user?: { login: string };
  author?: string;
  created_at: string;
  updated_at: string;
  head?: { ref: string; sha?: string };
  base?: { ref: string };
  draft?: boolean;
  labels?: Array<{ name: string } | string>;
  html_url?: string;
  url?: string;
  additions?: number;
  deletions?: number;
  changed_files?: number;
  mergeable_state?: string;
}

export async function listPulls(
  projectId: string,
  owner: string,
  repo: string,
  state = "open",
): Promise<PRListItem[]> {
  const { data } = await apiClient.get<PRListItem[]>(
    `/projects/${projectId}/reviews/pulls`,
    { params: { owner, repo, state } },
  );
  return Array.isArray(data) ? data : [];
}

export async function getPullDetail(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}`,
    { params: { owner, repo } },
  );
  return data as Record<string, unknown>;
}

export async function getPullDiff(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
): Promise<string> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/diff`,
    { params: { owner, repo } },
  );
  if (typeof data === "string") return data;
  if (typeof data === "object" && data !== null) {
    return (data as Record<string, unknown>).diff as string ?? JSON.stringify(data, null, 2);
  }
  return String(data);
}

export async function getPullFiles(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/files`,
    { params: { owner, repo } },
  );
  return data as Record<string, unknown>;
}

export async function getPullComments(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments`,
    { params: { owner, repo } },
  );
  return data as Record<string, unknown>;
}

export interface CreatePRCommentPayload {
  path: string;
  line: number;
  side: "LEFT" | "RIGHT";
  body: string;
  commit_id: string;
  start_line?: number;
  start_side?: "LEFT" | "RIGHT";
}

export async function createPRComment(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  payload: CreatePRCommentPayload,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments`,
    payload,
    { params: { owner, repo } },
  );
  return data as Record<string, unknown>;
}

export async function replyToComment(
  projectId: string,
  prNumber: number,
  commentId: number,
  owner: string,
  repo: string,
  body: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments/${commentId}/replies`,
    { body },
    { params: { owner, repo } },
  );
  return data as Record<string, unknown>;
}

export async function getPullChecks(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/checks`,
    { params: { owner, repo } },
  );
  return data as Record<string, unknown>;
}
