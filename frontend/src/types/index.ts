/** Matches `/auth/me` and nested `user` in `/auth/whoami`. */
export interface User {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url?: string | null;
  sso_subject?: string;
  is_active?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  updated_at: string;
}

/** Row from `GET /organizations` (workspace picker). */
export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  is_personal: boolean;
}

/** Reusable team chat prompts (`GET /organizations/:id/prompt-templates`). */
export interface OrgPromptTemplate {
  id: string;
  org_id: string;
  title: string;
  body: string;
  sort_order: number;
}

export interface OrgPromptTemplatesListResponse {
  templates: OrgPromptTemplate[];
  can_manage: boolean;
}

export interface Team {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  created_at: string;
  updated_at: string;
}

export interface TeamMember {
  id: string;
  team_id: string;
  user_id: string;
  role: string;
  created_at: string;
  user?: User;
}

/** Effective access for the current user when the project uses explicit shares. */
export type ProjectUserAccess = "read" | "write" | "admin";

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  org_id?: string;
  organization_id?: string | null;
  session_count?: number;
  /** Present on API v2+; omitting means full access (legacy). */
  current_user_access?: ProjectUserAccess;
  /** Creator; omitted on older API rows. */
  created_by_id?: string | null;
  /** True when someone else created this project and you have access via org/share. */
  shared_with_me?: boolean;
  /** Owner name or email when `shared_with_me` is true. */
  created_by_display?: string | null;
  /** Personal workspace vs team/org workspace. */
  workspace_type?: "personal" | "organization";
  /** Organization display name when `workspace_type` is `organization`. */
  organization_name?: string | null;
  /** Private (shareable) vs public (visible to all signed-in users). */
  visibility?: "private" | "public";
  created_at: string;
  updated_at: string;
}

export interface Session {
  id: string;
  project_id: string;
  title: string;
  model?: string | null;
  ai_config?: Record<string, unknown> | null;
  status: "active" | "idle" | "archived" | string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}

export interface PaginationParams {
  page?: number;
  page_size?: number;
}

export interface PaginatedMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  meta: PaginatedMeta;
}

export interface ApiErrorBody {
  detail?: string;
  message?: string;
  errors?: Record<string, string[]>;
}

export interface ApiResponse<T> {
  data: T;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface CreateProjectInput {
  name: string;
  description?: string;
  org_id?: string;
  /** Default private: use Sharing to invite collaborators. Public is visible to everyone signed in. */
  visibility?: "private" | "public";
  private_to_creator?: boolean;
}

export interface UpdateProjectInput {
  name?: string;
  description?: string | null;
}

export type ProjectShareSubjectType = "user" | "group";
export type ProjectShareRole = "view" | "edit" | "admin";

export interface ProjectShare {
  id: string;
  subject_type: ProjectShareSubjectType;
  role: ProjectShareRole;
  user_id: string | null;
  group_name: string | null;
  display_name: string;
}

export interface CreateProjectShareInput {
  subject_type: ProjectShareSubjectType;
  role: ProjectShareRole;
  user_identifier?: string | null;
  group_name?: string | null;
}

/** Org members who can receive a share (`GET /projects/:id/shareable-users`). */
export interface ShareableUser {
  id: string;
  email: string;
  full_name: string | null;
}

export interface CreateSessionInput {
  title: string;
  model?: string;
  ai_config?: Record<string, unknown>;
}

export interface UpdateSessionInput {
  title?: string;
  model?: string | null;
  status?: string;
  ai_config?: Record<string, unknown>;
}

export interface SendMessageInput {
  content: string;
}

// ---------------------------------------------------------------------------
// Context Hub types
// ---------------------------------------------------------------------------

export type PackVisibility = "public" | "organization" | "personal";

export type ContextSourceType =
  | "github_repo"
  | "gitlab_repo"
  | "jira_project"
  | "confluence_space"
  | "google_doc"
  | "google_drive_folder"
  | "file_pin"
  | "code_snippet"
  | "k8s_cluster";

export type SessionLayerType =
  | "pull_request"
  | "jira_ticket"
  | "google_doc"
  | "google_drive_folder"
  | "file_pin"
  | "code_snippet"
  | "past_session";

export interface PackContextSource {
  id: string;
  pack_id: string;
  type: ContextSourceType;
  name: string;
  url?: string | null;
  config?: Record<string, unknown> | null;
  created_at: string;
}

export interface ContextPack {
  id: string;
  name: string;
  icon?: string | null;
  description?: string | null;
  category?: string | null;
  version: string;
  visibility: PackVisibility;
  dependencies?: Record<string, unknown> | null;
  maintainer_team?: string | null;
  org_id?: string | null;
  created_by?: string | null;
  repo_count: number;
  sources: PackContextSource[];
  created_at: string;
  updated_at: string;
  /** Present on pack detail; number of projects with this pack installed. */
  installation_count?: number;
}

/** Projects that have a given context pack installed (hub API). */
export interface PackInstallation {
  project_id: string;
  project_name: string;
}

export interface InstalledPack {
  id: string;
  project_id: string;
  pack_id: string;
  version: string;
  auto_update: boolean;
  overrides?: Record<string, unknown> | null;
  installed_at: string;
  pack: ContextPack;
}

export interface ContextSource {
  id: string;
  project_id: string;
  type: ContextSourceType;
  name: string;
  url?: string | null;
  config?: Record<string, unknown> | null;
  auto_attach: boolean;
  last_indexed?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionLayer {
  id: string;
  session_id: string;
  type: SessionLayerType;
  reference_url?: string | null;
  label: string;
  cached_content?: Record<string, unknown> | null;
  token_count: number;
  created_at: string;
}


export interface CreatePackInput {
  name: string;
  description?: string;
  icon?: string;
  category?: string;
  visibility?: PackVisibility;
  maintainer_team?: string;
  org_id?: string;
  sources?: Array<{
    type: ContextSourceType;
    name: string;
    url?: string;
    config?: Record<string, unknown>;
  }>;
}

export interface UpdatePackInput {
  name?: string;
  description?: string;
  icon?: string;
  category?: string;
  visibility?: PackVisibility;
  maintainer_team?: string;
}

export interface AddContextSourceInput {
  type: ContextSourceType;
  name: string;
  url?: string;
  config?: Record<string, unknown>;
  auto_attach?: boolean;
}

export interface AddSessionLayerInput {
  type: SessionLayerType;
  label: string;
  reference_url?: string;
  cached_content?: Record<string, unknown>;
  token_count?: number;
}

// ---------------------------------------------------------------------------
// Secret Vault types
// ---------------------------------------------------------------------------

export type SecretScope = "personal" | "team" | "project";

export interface ProjectSecret {
  id: string;
  project_id: string;
  name: string;
  scope: SecretScope;
  placeholder: string;
  vault_backend: string;
  description?: string | null;
  created_by?: string | null;
  last_rotated?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SecretAuditEntry {
  id: string;
  secret_id: string;
  user_id?: string | null;
  action: string;
  details?: string | null;
  created_at: string;
}

export interface CreateSecretInput {
  name: string;
  value: string;
  scope?: SecretScope;
  description?: string;
}

export interface RotateSecretInput {
  value: string;
}

export interface ScanMatch {
  pattern_name: string;
  matched_text: string;
  start: number;
  end: number;
  severity: "high" | "medium" | "low";
  suggestion: string;
}

export interface ScanResponse {
  matches: ScanMatch[];
  has_secrets: boolean;
}

// ---------------------------------------------------------------------------
// AI Chat types
// ---------------------------------------------------------------------------

export interface AIModel {
  id: string;
  display_name: string;
  description: string;
  max_tokens: number;
}

export interface ChatInput {
  message: string;
  model?: string;
}

export type ActivityStatus = "done" | "running" | "pending";
export type ActivityIcon = "search" | "terminal" | "dot";

export interface ActivityAction {
  id: string;
  icon: ActivityIcon;
  label: string;
  status: ActivityStatus;
  durationMs?: number;
}

export interface SecretWarning {
  pattern: string;
  severity: string;
  suggestion: string;
  masked: string;
}

export interface StreamEvent {
  type: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Cluster types
// ---------------------------------------------------------------------------

export type ClusterRole = "context" | "test";
export type ClusterAuthMethod = "kubeconfig" | "token";
export type ClusterStatus = "pending" | "connected" | "error" | "syncing";
export type TestRunStatus = "pending" | "running" | "passed" | "failed" | "error" | "cancelled";

export interface ProjectCluster {
  id: string;
  project_id: string;
  name: string;
  role: ClusterRole;
  auth_method: ClusterAuthMethod;
  api_server_url?: string | null;
  namespace_filter?: string[] | null;
  status: ClusterStatus;
  status_message?: string | null;
  last_synced?: string | null;
  sync_config?: Record<string, unknown> | null;
  config?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface TestRun {
  id: string;
  cluster_id: string;
  run_type: string;
  command: string;
  status: TestRunStatus;
  output?: string | null;
  exit_code?: number | null;
  duration_ms?: number | null;
  config?: Record<string, unknown> | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface CreateClusterInput {
  name: string;
  role: ClusterRole;
  auth_method: ClusterAuthMethod;
  credentials: Record<string, unknown>;
  api_server_url?: string;
  namespace_filter?: string[];
  sync_config?: Record<string, unknown>;
}

/** Partial update; omit `credentials` to leave stored credentials unchanged. */
export interface UpdateClusterInput {
  name?: string;
  namespace_filter?: string[] | null;
  sync_config?: Record<string, unknown> | null;
  credentials?: Record<string, unknown>;
  api_server_url?: string | null;
}

// ---------------------------------------------------------------------------
// MCP Skills types
// ---------------------------------------------------------------------------

export type SkillStatus = "available" | "configured" | "connected" | "error";

export interface ConfigField {
  key: string;
  label: string;
  type: string;
  placeholder?: string;
  required?: boolean;
  help_url?: string;
  help_text?: string;
}

export interface McpSkill {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  icon?: string | null;
  transport: string;
  config_schema?: { fields: ConfigField[] } | null;
  has_config: boolean;
  enabled: boolean;
  is_builtin: boolean;
  status: SkillStatus;
  status_message?: string | null;
  tool_count: number;
  created_at: string;
  updated_at: string;
}

export interface McpSkillConfigInput {
  config_values: Record<string, string>;
}

export interface McpSkillCreateInput {
  name: string;
  slug: string;
  description?: string;
  icon?: string;
  transport?: string;
  server_command: string;
  server_args?: string[];
  server_url?: string;
  config_schema?: { fields: ConfigField[] };
}

export interface SkillTestResult {
  success: boolean;
  tool_count?: number;
  tools?: { name: string; description: string }[];
  error?: string;
}

// ---------------------------------------------------------------------------
// Workflow types
// ---------------------------------------------------------------------------

export interface Workflow {
  id: string;
  name: string;
  slug: string;
  description: string;
  system_prompt: string;
  icon?: string | null;
  is_builtin: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface CreateWorkflowInput {
  name: string;
  slug: string;
  description: string;
  system_prompt?: string;
  icon?: string;
  sort_order?: number;
}

