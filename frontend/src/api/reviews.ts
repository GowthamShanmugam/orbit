import { isAxiosError } from "axios";
import { apiClient } from "./client";

function rethrowWithDetail(err: unknown): never {
  if (isAxiosError(err)) {
    const data = err.response?.data;
    const detail =
      (typeof data === "object" && data !== null && (data as Record<string, unknown>).detail) ||
      (typeof data === "string" && data) ||
      err.message;
    throw new Error(String(detail));
  }
  throw err;
}

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

export async function getPullReviews(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/reviews`,
    { params: { owner, repo } },
  );
  return data as Record<string, unknown>;
}

// ── Pending review detection ────────────────────────────────────────────

export interface PendingReviewInfo {
  pending: boolean;
  review_node_id?: string;
  review_id?: number;
  comments?: Array<{
    id: number;
    path: string;
    line?: number;
    side?: string;
    body: string;
    user?: { login: string };
  }>;
}

export async function getPendingReview(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
): Promise<PendingReviewInfo> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review`,
    { params: { owner, repo } },
  );
  return data as PendingReviewInfo;
}

// ── Single comment (immediate) ──────────────────────────────────────────

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

// ── Pending review (start a review) ─────────────────────────────────────

export interface StartReviewPayload {
  path: string;
  line: number;
  side: "LEFT" | "RIGHT";
  body: string;
  commit_id: string;
  start_line?: number;
  start_side?: "LEFT" | "RIGHT";
}

export interface PendingReviewResult {
  review_node_id: string;
  review_id: number | null;
  comment_id: number | null;
}

export async function startPendingReview(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  payload: StartReviewPayload,
): Promise<PendingReviewResult> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review`,
    payload,
    { params: { owner, repo } },
  );
  return data as PendingReviewResult;
}

export interface AddReviewCommentPayload {
  review_node_id: string;
  path: string;
  line: number;
  side: "LEFT" | "RIGHT";
  body: string;
  commit_id: string;
  start_line?: number;
  start_side?: "LEFT" | "RIGHT";
}

export async function addPendingReviewComment(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  payload: AddReviewCommentPayload,
): Promise<{ comment_id: number | null }> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review/comments`,
    payload,
    { params: { owner, repo } },
  );
  return data as { comment_id: number | null };
}

// ── Direct review (no inline comments) ──────────────────────────────────

export type ReviewEvent = "COMMENT" | "APPROVE" | "REQUEST_CHANGES";

export async function createDirectReview(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  event: ReviewEvent,
  body = "",
): Promise<Record<string, unknown>> {
  try {
    const { data } = await apiClient.post(
      `/projects/${projectId}/reviews/pulls/${prNumber}/review`,
      { event, body },
      { params: { owner, repo } },
    );
    return data as Record<string, unknown>;
  } catch (err) {
    rethrowWithDetail(err);
  }
}

// ── Submit / Discard pending review ─────────────────────────────────────

export async function submitReview(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  reviewNodeId: string,
  event: ReviewEvent,
  body = "",
): Promise<Record<string, unknown>> {
  try {
    const { data } = await apiClient.post(
      `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review/submit`,
      { review_node_id: reviewNodeId, event, body },
      { params: { owner, repo } },
    );
    return data as Record<string, unknown>;
  } catch (err) {
    rethrowWithDetail(err);
  }
}

export async function discardReview(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  reviewNodeId: string,
  reviewDbId?: number | null,
): Promise<void> {
  try {
    await apiClient.post(
      `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review/discard`,
      { review_node_id: reviewNodeId, review_db_id: reviewDbId ?? null },
      { params: { owner, repo } },
    );
  } catch (err) {
    rethrowWithDetail(err);
  }
}

// ── Reply / Delete comments ─────────────────────────────────────────────

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

export async function editComment(
  projectId: string,
  prNumber: number,
  commentId: number,
  owner: string,
  repo: string,
  body: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.patch(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments/${commentId}`,
    { body },
    { params: { owner, repo } },
  );
  return data as Record<string, unknown>;
}

export async function deleteComment(
  projectId: string,
  prNumber: number,
  commentId: number,
  owner: string,
  repo: string,
): Promise<void> {
  await apiClient.delete(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments/${commentId}`,
    { params: { owner, repo } },
  );
}
