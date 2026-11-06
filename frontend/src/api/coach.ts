import { apiClient } from "./client";

export type CoachLane = "Jira" | "My MR" | "Review" | "Standup";

export interface CoachWatchlists {
  jira: CoachJiraItem[];
  meetings: CoachMeetingItem[];
  repos: CoachRepoItem[];
}

export interface CoachJiraItem {
  id: string;
  project_key: string;
  label?: string;
  orbit_project_id?: string | null;
}

export interface CoachMeetingItem {
  id: string;
  title: string;
  notes_url?: string | null;
  notes_doc_id?: string | null;
  days_of_week?: number[];
  time_local?: string | null;
  reminder_minutes_before?: number | null;
  calendar_event_id?: string | null;
}

export interface CoachCalendarMeetingOption {
  calendar_event_id: string;
  title: string;
  start: string;
  time_local: string;
  days_of_week: number[];
  notes_url?: string | null;
  notes_doc_id?: string | null;
  html_link?: string | null;
  label: string;
  /** Server-side: occurrence falls on "today" in the event timezone */
  is_today?: boolean;
}

export interface CoachMeetingsResponse {
  connected: boolean;
  needs_reauth?: boolean;
  meetings: CoachCalendarMeetingOption[];
  error?: string | null;
}

export interface CoachRepoItem {
  id: string;
  provider: "github" | "gitlab";
  owner: string;
  repo: string;
  label?: string;
  orbit_project_id?: string | null;
}

export interface CoachReminderPrefs {
  enabled: boolean;
  standup_minutes_before: number;
  /** Orbit workspace where Focus sessions open by default */
  default_orbit_project_id?: string | null;
}

export interface CoachJiraProjectOption {
  key: string;
  name: string;
}

export interface CoachJiraProjectsResponse {
  connected: boolean;
  projects: CoachJiraProjectOption[];
  error?: string | null;
}

export interface CoachMrItem {
  provider: "github" | "gitlab";
  owner: string;
  repo: string;
  number: number;
  title: string;
  url?: string;
  draft?: boolean;
  ci_state?: string | null;
  mergeable?: boolean | null;
  changes_requested?: boolean;
  jira_keys?: string[];
  orbit_project_id?: string | null;
  repo_label?: string;
  author?: string;
  is_author?: boolean;
  next_action?: string;
  reviewers?: string[];
}

export interface CoachJiraIssue {
  key: string;
  summary: string;
  status?: string;
  priority?: string;
  sprint?: string;
  url?: string | null;
  project_key?: string;
  orbit_project_id?: string | null;
  updated?: string;
}

export interface CoachStandup {
  meeting_id: string;
  title: string;
  notes_url?: string | null;
  time_local?: string | null;
  minutes_until?: number | null;
  draft: string;
  has_notes?: boolean;
}

export interface CoachFocusItem {
  id: string;
  lane: CoachLane | string;
  title: string;
  why: string;
  score: number;
  cta: "focus" | "copy_standup" | "open_review" | string;
  meeting_id?: string;
  draft?: string;
  issue?: CoachJiraIssue;
  mr?: CoachMrItem;
}

export interface CoachAttention {
  key: string;
  kind: string;
  title: string;
  detail?: string;
  count?: number;
  url?: string | null;
  flags?: string[];
  blink?: boolean;
  jira_keys?: string[];
}

export interface CoachSprintItem {
  key: string;
  plan: string;
}

export interface CoachSprintDay {
  date?: string;
  label?: string;
  items?: CoachSprintItem[];
}

export interface CoachSprintPlan {
  sprint?: string;
  days_left?: number | null;
  end?: string;
  today?: CoachSprintItem[];
  waiting?: CoachSprintItem[];
  days?: CoachSprintDay[];
  wont_finish?: Array<{ key?: string; why?: string }>;
}

export interface CoachToday {
  date: string;
  generated_at: string;
  focus: CoachFocusItem[];
  standups: CoachStandup[];
  my_mrs: CoachMrItem[];
  reviews_waiting: CoachMrItem[];
  jira_issues: CoachJiraIssue[];
  attention?: CoachAttention[];
  sprint_plan?: CoachSprintPlan | null;
  hooks?: { gitlab: string; github: string; jira: string };
  snapshot_on?: string | null;
  reminders: Array<{
    type: string;
    meeting_id?: string;
    title?: string;
    minutes_until?: number;
    message: string;
  }>;
  notices?: string[];
  watchlists: CoachWatchlists;
  reminder_prefs: CoachReminderPrefs;
  integrations: {
    atlassian: boolean;
    github: boolean;
    gitlab: boolean;
    google_drive: boolean;
  };
}

export interface CoachFocusResult {
  session_id: string;
  project_id: string;
  title: string;
  url: string;
}

export async function listCoachJiraProjects(): Promise<CoachJiraProjectsResponse> {
  const { data } = await apiClient.get<CoachJiraProjectsResponse>(
    "/coach/options/jira-projects",
  );
  return data;
}

export async function listCoachMeetings(): Promise<CoachMeetingsResponse> {
  const { data } = await apiClient.get<CoachMeetingsResponse>("/coach/options/meetings");
  return data;
}

export async function getCoachWatchlists(): Promise<{
  watchlists: CoachWatchlists;
  reminder_prefs: CoachReminderPrefs;
}> {
  const { data } = await apiClient.get("/coach/watchlists");
  return data;
}

export async function putCoachWatchlists(body: {
  watchlists?: CoachWatchlists;
  reminder_prefs?: CoachReminderPrefs;
}): Promise<{
  watchlists: CoachWatchlists;
  reminder_prefs: CoachReminderPrefs;
}> {
  const { data } = await apiClient.put("/coach/watchlists", body);
  return data;
}

export async function clearCoachAttention(key: string): Promise<void> {
  await apiClient.post("/coach/attention/clear", { key });
}

export async function getCoachToday(refresh = false): Promise<CoachToday> {
  const doRefresh = refresh === true;
  const { data } = await apiClient.get<CoachToday>("/coach/today", {
    params: doRefresh ? { refresh: true } : {},
  });
  return data;
}

export async function regenerateStandupDraft(meetingId: string): Promise<CoachStandup> {
  const { data } = await apiClient.post<CoachStandup>(
    `/coach/standup/${encodeURIComponent(meetingId)}/draft`,
  );
  return data;
}

export async function createCoachFocus(body: {
  orbit_project_id: string;
  issue_key?: string;
  issue_url?: string | null;
  issue_summary?: string | null;
  mr?: CoachMrItem | null;
  brief?: string;
}): Promise<CoachFocusResult> {
  const { data } = await apiClient.post<CoachFocusResult>("/coach/focus", body);
  return data;
}
