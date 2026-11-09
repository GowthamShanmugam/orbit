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

export type ReviewProvider = "github" | "gitlab";

function reviewParams(
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
): Record<string, string> {
  return { owner, repo, provider };
}

export async function getPullDetail(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}`,
    { params: reviewParams(owner, repo, provider) },
  );
  return data as Record<string, unknown>;
}

export async function getPullDiff(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
): Promise<string> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/diff`,
    { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/files`,
    { params: reviewParams(owner, repo, provider) },
  );
  return data as Record<string, unknown>;
}

export async function getPullFileContent(
  projectId: string,
  prNumber: number,
  path: string,
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
): Promise<{ path: string; content: string; source?: string; sha?: string | null }> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/file-content`,
    { params: { ...reviewParams(owner, repo, provider), path } },
  );
  return data as { path: string; content: string; source?: string; sha?: string | null };
}

export async function getPullFlowChart(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  provider: ReviewProvider,
  body: {
    path: string;
    start_line?: number;
    end_line?: number;
    patch?: string;
  },
): Promise<{
  path: string;
  label: string;
  start_line: number;
  end_line: number;
  mermaid: string;
  error?: string | null;
}> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/flow-chart`,
    body,
    { params: reviewParams(owner, repo, provider) },
  );
  return data as {
    path: string;
    label: string;
    start_line: number;
    end_line: number;
    mermaid: string;
    error?: string | null;
  };
}

export async function getPullComments(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments`,
    { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<PendingReviewInfo> {
  const { data } = await apiClient.get(
    `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review`,
    { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments`,
    payload,
    { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<PendingReviewResult> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review`,
    payload,
    { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<{ comment_id: number | null }> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review/comments`,
    payload,
    { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<Record<string, unknown>> {
  try {
    const { data } = await apiClient.post(
      `/projects/${projectId}/reviews/pulls/${prNumber}/review`,
      { event, body },
      { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<Record<string, unknown>> {
  try {
    const { data } = await apiClient.post(
      `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review/submit`,
      { review_node_id: reviewNodeId, event, body },
      { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<void> {
  try {
    await apiClient.post(
      `/projects/${projectId}/reviews/pulls/${prNumber}/pending-review/discard`,
      { review_node_id: reviewNodeId, review_db_id: reviewDbId ?? null },
      { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments/${commentId}/replies`,
    { body },
    { params: reviewParams(owner, repo, provider) },
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
  provider: ReviewProvider = "github",
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.patch(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments/${commentId}`,
    { body },
    { params: reviewParams(owner, repo, provider) },
  );
  return data as Record<string, unknown>;
}

export async function deleteComment(
  projectId: string,
  prNumber: number,
  commentId: number,
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
): Promise<void> {
  await apiClient.delete(
    `/projects/${projectId}/reviews/pulls/${prNumber}/comments/${commentId}`,
    { params: reviewParams(owner, repo, provider) },
  );
}

export type AiReviewSuggestion = {
  path: string;
  line: number;
  side: "LEFT" | "RIGHT";
  severity: "high" | "medium" | "low";
  body: string;
};

export async function runAiReview(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
  title?: string,
): Promise<{
  suggestions: AiReviewSuggestion[];
  count: number;
  used_checkout?: boolean;
  used_repo_reads?: string[];
}> {
  try {
    const { data } = await apiClient.post<{
      suggestions: AiReviewSuggestion[];
      count: number;
      used_checkout?: boolean;
      used_repo_reads?: string[];
    }>(
      `/projects/${projectId}/reviews/pulls/${prNumber}/ai-review`,
      { title: title ?? null },
      { params: reviewParams(owner, repo, provider) },
    );
    return {
      suggestions: Array.isArray(data?.suggestions) ? data.suggestions : [],
      count: Number(data?.count ?? 0),
      used_checkout: Boolean(data?.used_checkout),
      used_repo_reads: Array.isArray(data?.used_repo_reads)
        ? data.used_repo_reads
        : [],
    };
  } catch (err) {
    rethrowWithDetail(err);
  }
}

export type CiJob = {
  id: string;
  name: string;
  stage?: string;
  status: string;
  allow_failure?: boolean;
  web_url?: string;
  duration?: number | null;
  finished_at?: string | null;
  pipeline_id?: string;
  failure?: boolean;
  summary?: string;
};

export type CiJobsResponse = {
  provider: ReviewProvider;
  pipeline_id?: string | null;
  pipeline_status?: string | null;
  pipeline_web_url?: string;
  jobs: CiJob[];
  failed_count?: number;
};

export type CiDiagnosis = {
  root_cause: string;
  where: string;
  evidence: string;
  severity: "high" | "medium" | "low";
  summary: string;
  suggested_comment: string;
  comment_path: string;
  comment_line: number | null;
};

export type CiDebugResult = {
  job_id: string;
  job_name: string;
  job_status: string;
  web_url: string;
  log_excerpt: string;
  used_test_report: boolean;
  used_artifacts?: string[];
  artifacts_note?: string;
  used_checkout?: boolean;
  used_repo_reads?: string[];
  diagnosis: CiDiagnosis;
};

export async function listCiJobs(
  projectId: string,
  prNumber: number,
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
): Promise<CiJobsResponse> {
  try {
    const { data } = await apiClient.get<CiJobsResponse>(
      `/projects/${projectId}/reviews/pulls/${prNumber}/ci-jobs`,
      { params: reviewParams(owner, repo, provider) },
    );
    return {
      ...data,
      jobs: Array.isArray(data?.jobs) ? data.jobs : [],
    };
  } catch (err) {
    rethrowWithDetail(err);
  }
}

export async function debugCiJob(
  projectId: string,
  prNumber: number,
  jobId: string,
  owner: string,
  repo: string,
  provider: ReviewProvider = "github",
): Promise<CiDebugResult> {
  try {
    const { data } = await apiClient.post<CiDebugResult>(
      `/projects/${projectId}/reviews/pulls/${prNumber}/ci-jobs/${encodeURIComponent(jobId)}/debug`,
      {},
      { params: reviewParams(owner, repo, provider) },
    );
    return data;
  } catch (err) {
    rethrowWithDetail(err);
  }
}
