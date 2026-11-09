import {
  clearCoachAttention,
  createCoachFocus,
  getCoachToday,
  putCoachWatchlists,
  type CoachAttention,
  type CoachFocusItem,
  type CoachJiraIssue,
  type CoachMrItem,
  type CoachReminderPrefs,
  type CoachSprintPlan,
  type CoachStandup,
  type CoachToday,
  type CoachWatchlists,
} from "@/api/coach";
import { listProjects } from "@/api/projects";
import WatchlistsDrawer from "@/components/Today/WatchlistsDrawer";
import type { Project } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Bell,
  ChevronDown,
  ListTodo,
  RefreshCw,
  Settings2,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

const AUTO_REFRESH_MS = 10 * 60_000;

function formatDateLabel(isoDate: string) {
  try {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "long",
      month: "short",
      day: "numeric",
    }).format(new Date(`${isoDate}T12:00:00`));
  } catch {
    return isoDate;
  }
}

export default function TodayPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [projectPicker, setProjectPicker] = useState<{
    issue?: CoachJiraIssue;
    mr?: CoachMrItem;
  } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const todayQuery = useQuery({
    queryKey: ["coach", "today"],
    queryFn: getCoachToday,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });
  const projects: Project[] = projectsQuery.data ?? [];

  const data = todayQuery.data;
  const watchlists: CoachWatchlists = data?.watchlists ?? {
    jira: [],
    meetings: [],
    repos: [],
  };
  const reminderPrefs: CoachReminderPrefs = data?.reminder_prefs ?? {
    enabled: true,
    standup_minutes_before: 15,
    default_orbit_project_id: null,
  };

  const saveWatchlists = async (next: {
    watchlists: CoachWatchlists;
    reminder_prefs: CoachReminderPrefs;
  }) => {
    await putCoachWatchlists(next);
    await queryClient.invalidateQueries({ queryKey: ["coach", "today"] });
  };

  const refreshInFlight = useRef(false);
  const refreshMut = useMutation({
    mutationFn: async () => {
      refreshInFlight.current = true;
      try {
        return await getCoachToday(true);
      } finally {
        refreshInFlight.current = false;
      }
    },
    onSuccess: (fresh) => {
      queryClient.setQueryData(["coach", "today"], fresh);
    },
  });
  const refreshNow = useRef(refreshMut.mutate);
  refreshNow.current = refreshMut.mutate;
  useEffect(() => {
    const id = window.setInterval(() => {
      if (refreshInFlight.current) return;
      refreshNow.current();
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  const focusMut = useMutation({
    mutationFn: createCoachFocus,
    onSuccess: (res) => {
      setProjectPicker(null);
      navigate(res.url);
    },
    onError: (e: Error) => setActionError(e.message),
  });

  const clearMut = useMutation({
    mutationFn: clearCoachAttention,
    onSuccess: (_res, key) => {
      queryClient.setQueryData<CoachToday | undefined>(["coach", "today"], (prev) => {
        if (!prev) return prev;
        return { ...prev, attention: (prev.attention ?? []).filter((row) => row.key !== key) };
      });
    },
  });

  const emptyWatchlists =
    watchlists.jira.length === 0 &&
    watchlists.meetings.length === 0 &&
    watchlists.repos.length === 0;

  const resolveProjectId = (issue?: CoachJiraIssue, mr?: CoachMrItem) =>
    issue?.orbit_project_id ||
    mr?.orbit_project_id ||
    reminderPrefs.default_orbit_project_id ||
    null;

  const startFocus = (issue?: CoachJiraIssue, mr?: CoachMrItem) => {
    setActionError(null);
    const pid = resolveProjectId(issue, mr);
    if (!pid) {
      setProjectPicker({ issue, mr });
      return;
    }
    focusMut.mutate({
      orbit_project_id: pid,
      issue_key: issue?.key,
      issue_url: issue?.url,
      issue_summary: issue?.summary,
      mr: mr ?? undefined,
    });
  };

  const handleFocusCta = (item: CoachFocusItem) => {
    if (item.cta === "open_review" && item.mr) {
      const pid = item.mr.orbit_project_id;
      if (!pid) {
        setProjectPicker({ mr: item.mr });
        return;
      }
      // Open a Focus-like session for review context (read path still needs a project)
      focusMut.mutate({
        orbit_project_id: pid,
        mr: item.mr,
        brief: `Review requested for ${item.mr.owner}/${item.mr.repo}#${item.mr.number}.\n\nOpen the Reviews panel in this session to inspect the diff.`,
      });
      return;
    }
    startFocus(item.issue, item.mr);
  };

  const dateLabel = useMemo(
    () => (data?.date ? formatDateLabel(data.date) : "Today"),
    [data?.date],
  );

  return (
    <div className="mx-auto max-w-4xl p-8">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <Sparkles className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-[var(--o-text)]">Today</h1>
            <p className="text-sm text-[var(--o-text-secondary)]">{dateLabel}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => refreshMut.mutate()}
            disabled={refreshMut.isPending || todayQuery.isFetching}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--o-border)] px-3 py-1.5 text-sm text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-accent)] hover:text-[var(--o-accent)] disabled:opacity-50"
          >
            <RefreshCw
              className={clsx(
                "h-3.5 w-3.5",
                (refreshMut.isPending || todayQuery.isFetching) && "animate-spin",
              )}
            />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--o-border)] px-3 py-1.5 text-sm text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-accent)] hover:text-[var(--o-accent)]"
          >
            <Settings2 className="h-3.5 w-3.5" />
            Watchlists
          </button>
        </div>
      </div>

      {actionError && (
        <p className="mt-4 text-sm text-red-400" role="alert">
          {actionError}
        </p>
      )}

      {data?.notices && data.notices.length > 0 && (
        <div className="mt-4 space-y-2">
          {data.notices.map((n) => (
            <p
              key={n}
              className="rounded-lg border border-[var(--o-border)] bg-[var(--o-bg-subtle)] px-3 py-2 text-sm text-[var(--o-text-secondary)]"
            >
              {n}
            </p>
          ))}
        </div>
      )}

      {todayQuery.isLoading && !data ? (
        <p className="mt-8 text-sm text-[var(--o-text-secondary)]">Loading your day…</p>
      ) : todayQuery.isError ? (
        <p className="mt-8 text-sm text-red-400" role="alert">
          {(todayQuery.error as Error)?.message || "Failed to load Today"}
        </p>
      ) : (
        <>
          {emptyWatchlists && (
            <div className="mt-8 rounded-lg border border-dashed border-[var(--o-border)] p-6 text-center">
              <p className="text-sm font-medium text-[var(--o-text)]">Set up your daily coach</p>
              <ol className="mx-auto mt-3 max-w-md space-y-1 text-left text-sm text-[var(--o-text-secondary)]">
                <li>1. Pick the Orbit project where Focus sessions should open</li>
                <li>2. Add Jira project keys (e.g. DATA)</li>
                <li>3. Add standup meetings and repos you care about</li>
              </ol>
              <button
                type="button"
                className="o-btn-primary mt-4 text-sm"
                onClick={() => setDrawerOpen(true)}
              >
                Open watchlists
              </button>
              {data?.integrations && (
                <p className="mt-3 text-xs text-[var(--o-text-tertiary)]">
                  Connected:{" "}
                  {[
                    data.integrations.atlassian && "Jira",
                    data.integrations.github && "GitHub",
                    data.integrations.gitlab && "GitLab",
                    data.integrations.google_drive && "Google Drive",
                  ]
                    .filter(Boolean)
                    .join(" · ") || "none yet — connect under Integrations"}
                </p>
              )}
            </div>
          )}

          {!emptyWatchlists && data && (
            <NeedsYou
              attention={data.attention ?? []}
              reviews={data.reviews_waiting ?? []}
              standups={data.standups ?? []}
              onClear={(key) => clearMut.mutate(key)}
              onReview={(mr) =>
                handleFocusCta({
                  id: `review:${mr.provider}:${mr.number}`,
                  lane: "Review",
                  title: mr.title,
                  why: "",
                  score: 0,
                  cta: "open_review",
                  mr,
                })
              }
            />
          )}

          {!emptyWatchlists && (
            <SprintBoard
              plan={data?.sprint_plan}
              issues={data?.jira_issues ?? []}
              mrs={data?.my_mrs ?? []}
              standups={data?.standups ?? []}
              onFocusIssue={(issue) => startFocus(issue)}
              onFocusMr={(mr, issue) => startFocus(issue, mr)}
            />
          )}
        </>
      )}

      <WatchlistsDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        watchlists={watchlists}
        reminderPrefs={reminderPrefs}
        onSave={saveWatchlists}
      />

      {projectPicker && (
        <ProjectPickerModal
          projects={projects}
          onCancel={() => setProjectPicker(null)}
          onPick={(projectId) => {
            focusMut.mutate({
              orbit_project_id: projectId,
              issue_key: projectPicker.issue?.key,
              issue_url: projectPicker.issue?.url,
              issue_summary: projectPicker.issue?.summary,
              mr: projectPicker.mr ?? undefined,
            });
          }}
          busy={focusMut.isPending}
        />
      )}
    </div>
  );
}

type PlanLine = { key: string; text: string };

function isQuietStandup(draft: string) {
  return /one hour after|nothing looks off|waiting for the one-hour/i.test(draft);
}

function shortWhen(iso?: string) {
  if (!iso) return "";
  const day = iso.slice(0, 10);
  try {
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(
      new Date(`${day}T12:00:00`),
    );
  } catch {
    return day;
  }
}

function coveredKeys(plan?: CoachSprintPlan | null) {
  const keys = new Set<string>();
  for (const item of plan?.today ?? []) keys.add(item.key);
  for (const item of plan?.waiting ?? []) keys.add(item.key);
  for (const day of plan?.days ?? []) {
    for (const item of day.items ?? []) keys.add(item.key);
  }
  for (const item of plan?.wont_finish ?? []) {
    if (item.key) keys.add(item.key);
  }
  return keys;
}

function sprintNames(issue?: CoachJiraIssue) {
  return (issue?.sprint || "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
}

function mrsFor(key: string, mrs: CoachMrItem[]) {
  return mrs.filter((mr) => (mr.jira_keys ?? []).includes(key));
}

function mrHint(linked: CoachMrItem[]) {
  const mr = linked[0];
  if (!mr) return "";
  const who = (mr.reviewers ?? []).slice(0, 2).join(", ");
  if (who && mr.next_action?.startsWith("Waiting")) return `!${mr.number} · ${who}`;
  if (mr.next_action) return `!${mr.number} · ${mr.next_action}`;
  return `!${mr.number}`;
}

function NeedsYou({
  attention,
  reviews,
  standups,
  onClear,
  onReview,
}: {
  attention: CoachAttention[];
  reviews: CoachMrItem[];
  standups: CoachStandup[];
  onClear: (key: string) => void;
  onReview: (mr: CoachMrItem) => void;
}) {
  const rows = attention.filter((row) => row.kind !== "meeting" || row.blink);
  const alerts = standups.filter((standup) => standup.draft && !isQuietStandup(standup.draft));
  const pulsing = rows.some((row) => row.blink) || reviews.length > 0 || alerts.length > 0;
  const empty = rows.length === 0 && reviews.length === 0 && alerts.length === 0;
  return (
    <section className="mt-5">
      <div className="mb-2 flex items-center gap-2">
        <Bell className={clsx("h-4 w-4", pulsing ? "animate-pulse text-[var(--o-accent)]" : "text-[var(--o-text-tertiary)]")} />
        <h2 className="text-sm font-semibold text-[var(--o-text)]">Needs you</h2>
      </div>
      {empty ? (
        <p className="text-sm text-[var(--o-text-tertiary)]">
          Quiet. While this page is open, merge requests are read every 10 minutes. A failed pipeline or a review comment that still needs your reply shows here until it is done.
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((row) => (
            <AttentionRow key={row.key} row={row} onClear={() => onClear(row.key)} />
          ))}
          {reviews.map((mr) => (
            <li
              key={`rev-${mr.provider}-${mr.number}`}
              className="o-needs-blink flex items-start justify-between gap-3 rounded-lg border px-3 py-2.5"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-[var(--o-text)]">
                  Review !{mr.number} is waiting on you
                </p>
                <p className="mt-1 text-xs text-[var(--o-text-secondary)]">{mr.title}</p>
              </div>
              <button type="button" className="o-btn-ghost shrink-0 text-xs" onClick={() => onReview(mr)}>
                Open review
              </button>
            </li>
          ))}
          {alerts.map((standup) => (
            <li
              key={standup.meeting_id}
              className="o-needs-blink rounded-lg border px-3 py-2.5"
            >
              <p className="text-sm font-medium text-[var(--o-text)]">{standup.title}</p>
              <p className="mt-1 whitespace-pre-wrap text-xs text-[var(--o-text-secondary)]">
                {standup.draft}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SprintBoard({
  plan,
  issues,
  mrs,
  standups,
  onFocusIssue,
  onFocusMr,
}: {
  plan?: CoachSprintPlan | null;
  issues: CoachJiraIssue[];
  mrs: CoachMrItem[];
  standups: CoachStandup[];
  onFocusIssue: (issue: CoachJiraIssue) => void;
  onFocusMr: (mr: CoachMrItem, issue?: CoachJiraIssue) => void;
}) {
  const byKey = useMemo(() => {
    const map = new Map<string, CoachJiraIssue>();
    for (const issue of issues) map.set(issue.key, issue);
    return map;
  }, [issues]);
  const tabs = useMemo(() => {
    const known = coveredKeys(plan);
    const sprintName = plan?.sprint || "";
    const outside = issues.filter((issue) => {
      if (!sprintName) return !known.has(issue.key);
      return !sprintNames(issue).includes(sprintName);
    });
    const unplanned = issues.filter(
      (issue) => sprintNames(issue).includes(sprintName) && sprintName && !known.has(issue.key),
    );
    const next: Array<{ id: string; label: string; items: PlanLine[] }> = [
      {
        id: "today",
        label: "Today",
        items: (plan?.today ?? []).map((item) => ({ key: item.key, text: item.plan })),
      },
    ];
    if ((plan?.waiting ?? []).length > 0) {
      next.push({
        id: "waiting",
        label: "Waiting",
        items: (plan?.waiting ?? []).map((item) => ({ key: item.key, text: item.plan })),
      });
    }
    for (const day of plan?.days ?? []) {
      next.push({
        id: `${day.date}-${day.label}`,
        label: day.label ? `${day.label} ${shortWhen(day.date)}` : shortWhen(day.date) || "Day",
        items: (day.items ?? []).map((item) => ({ key: item.key, text: item.plan })),
      });
    }
    if ((plan?.wont_finish ?? []).length > 0) {
      next.push({
        id: "wont",
        label: "Won't fit",
        items: (plan?.wont_finish ?? [])
          .filter((item) => item.key)
          .map((item) => ({ key: item.key as string, text: item.why || "" })),
      });
    }
    if (unplanned.length > 0) {
      next.push({
        id: "unplanned",
        label: "In sprint",
        items: unplanned.map((issue) => ({
          key: issue.key,
          text: "This ticket is on the current sprint. It is not on a day yet.",
        })),
      });
    }
    if (outside.length > 0) {
      next.push({
        id: "outside",
        label: "Outside sprint",
        items: outside.map((issue) => ({ key: issue.key, text: "" })),
      });
    }
    return next;
  }, [plan, issues]);
  const [tab, setTab] = useState(tabs[0]?.id ?? "today");
  const [picked, setPicked] = useState<string | null>(null);
  const active = tabs.find((item) => item.id === tab) ?? tabs[0];
  const openKey =
    picked === "__none__"
      ? undefined
      : picked && active?.items.some((item) => item.key === picked)
        ? picked
        : active?.items[0]?.key;
  const daysLeft = plan?.days_left;
  const quiet = standups.filter((standup) => isQuietStandup(standup.draft));

  return (
    <section className="mt-6">
      <div className="mb-3 flex items-start gap-2">
        <ListTodo className="mt-0.5 h-4 w-4 text-[var(--o-accent)]" />
        <div>
          <h2 className="text-sm font-semibold text-[var(--o-text)]">
            {daysLeft != null
              ? `${daysLeft} working day${daysLeft === 1 ? "" : "s"} left`
              : "This sprint"}
          </h2>
          <p className="text-xs text-[var(--o-text-tertiary)]">
            {[plan?.sprint, plan?.end ? `ends ${shortWhen(plan.end)}` : ""]
              .filter(Boolean)
              .join(" · ") || "Open a day. Each ticket includes its MR."}
          </p>
        </div>
      </div>
      {quiet.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {quiet.map((standup) => (
            <span
              key={standup.meeting_id}
              className="inline-flex max-w-full items-center gap-2 rounded-full border border-[var(--o-border)] px-3 py-1 text-xs text-[var(--o-text-secondary)]"
            >
              <span className="truncate">
                {standup.title}
                {standup.draft ? ` · ${standup.draft}` : ""}
              </span>
              {standup.notes_url && (
                <a href={standup.notes_url} target="_blank" rel="noreferrer" className="shrink-0 text-[var(--o-accent)]">
                  Notes
                </a>
              )}
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-1 overflow-x-auto pb-2">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              setTab(item.id);
              setPicked(null);
            }}
            className={clsx(
              "shrink-0 rounded-full px-3 py-1 text-xs",
              item.id === active?.id
                ? "bg-[var(--o-accent)] text-white"
                : "border border-[var(--o-border)] text-[var(--o-text-secondary)]",
            )}
          >
            {item.label}
            <span className="ml-1 opacity-70">{item.items.length}</span>
          </button>
        ))}
      </div>
      <ul className="divide-y divide-[var(--o-border)] rounded-lg border border-[var(--o-border)]">
        {(active?.items ?? []).length === 0 ? (
          <li className="px-3 py-4 text-sm text-[var(--o-text-tertiary)]">Nothing on this day.</li>
        ) : (
          (active?.items ?? []).map((item) => {
            const issue = byKey.get(item.key);
            const linked = mrsFor(item.key, mrs);
            const open = item.key === openKey;
            return (
              <li key={item.key}>
                <button
                  type="button"
                  className="flex w-full items-center gap-3 px-3 py-2.5 text-left"
                  onClick={() => setPicked(open ? "__none__" : item.key)}
                >
                  <ChevronDown
                    className={clsx("h-3.5 w-3.5 shrink-0 text-[var(--o-text-tertiary)]", open && "rotate-180")}
                  />
                  <span className="w-24 shrink-0 text-sm font-semibold text-[var(--o-text)]">{item.key}</span>
                  <span className="min-w-0 flex-1 truncate text-sm text-[var(--o-text-secondary)]">
                    {issue?.summary || item.text}
                  </span>
                  <span className="hidden max-w-[220px] truncate text-xs text-[var(--o-text-tertiary)] sm:inline">
                    {mrHint(linked) || issue?.status || ""}
                  </span>
                </button>
                {open && (
                  <div className="space-y-3 px-3 pb-3 pl-10">
                    {item.text && (
                      <p className="whitespace-pre-wrap text-sm text-[var(--o-text-secondary)]">{item.text}</p>
                    )}
                    {issue && (
                      <p className="text-xs text-[var(--o-text-tertiary)]">
                        {issue.status || "Open"}
                        {issue.priority ? ` · ${issue.priority}` : ""}
                      </p>
                    )}
                    {linked.map((mr) => (
                      <div key={`${mr.provider}-${mr.number}`} className="min-w-0">
                        <p className="text-sm text-[var(--o-text)]">
                          !{mr.number} {mr.title}
                        </p>
                        <p className="text-xs text-[var(--o-text-tertiary)]">
                          {[
                            mr.next_action,
                            (mr.reviewers ?? []).length > 0 ? (mr.reviewers ?? []).join(", ") : "",
                            mr.ci_state ? `CI ${mr.ci_state}` : "",
                            mr.draft ? "draft" : "",
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      </div>
                    ))}
                    <div className="flex justify-end gap-2">
                      {linked[0]?.url ? (
                        <a href={linked[0].url} target="_blank" rel="noreferrer" className="o-btn-ghost inline-flex w-14 items-center justify-center rounded-md px-2 py-1 text-xs">
                          MR
                        </a>
                      ) : (
                        <span className="o-btn-ghost inline-flex w-14 items-center justify-center rounded-md px-2 py-1 text-xs opacity-40">MR</span>
                      )}
                      <button
                        type="button"
                        className="o-btn-ghost inline-flex w-16 items-center justify-center rounded-md px-2 py-1 text-xs"
                        disabled={!issue && linked.length === 0}
                        onClick={() => (linked[0] ? onFocusMr(linked[0], issue) : issue && onFocusIssue(issue))}
                      >
                        Focus
                      </button>
                      {issue?.url ? (
                        <a href={issue.url} target="_blank" rel="noreferrer" className="o-btn-ghost inline-flex w-14 items-center justify-center rounded-md px-2 py-1 text-xs">
                          Jira
                        </a>
                      ) : (
                        <span className="o-btn-ghost inline-flex w-14 items-center justify-center rounded-md px-2 py-1 text-xs opacity-40">Jira</span>
                      )}
                    </div>
                  </div>
                )}
              </li>
            );
          })
        )}
      </ul>
    </section>
  );
}

function AttentionRow({ row, onClear }: { row: CoachAttention; onClear: () => void }) {
  const count = row.count ?? 0;
  return (
    <li
      className={clsx(
        "flex flex-wrap items-start justify-between gap-3 rounded-lg border px-3 py-2.5",
        row.blink ? "o-needs-blink" : "border-[var(--o-border)]",
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-[var(--o-text)]">{row.title}</p>
        {row.detail && (
          <p className="mt-1 whitespace-pre-wrap text-xs text-[var(--o-text-secondary)]">
            {count > 1 ? `${count} new. Latest: ` : ""}
            {row.detail}
          </p>
        )}
        {(row.flags ?? []).includes("ci_red") && (
          <p className="mt-1 text-xs text-[var(--o-text-tertiary)]">CI is red</p>
        )}
      </div>
      <div className="flex gap-2">
        {row.url && (
          <a href={row.url} target="_blank" rel="noreferrer" className="o-btn-ghost text-xs">
            Open
          </a>
        )}
        <button type="button" className="o-btn-ghost text-xs" onClick={onClear}>
          Clear
        </button>
      </div>
    </li>
  );
}

function ProjectPickerModal({
  projects,
  onCancel,
  onPick,
  busy,
}: {
  projects: Project[];
  onCancel: () => void;
  onPick: (projectId: string) => void;
  busy: boolean;
}) {
  const [selected, setSelected] = useState(projects[0]?.id ?? "");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] p-5 shadow-xl">
        <h3 className="text-sm font-semibold text-[var(--o-text)]">Where should Focus open?</h3>
        <p className="mt-1 text-xs text-[var(--o-text-tertiary)]">
          Choose an Orbit workspace (under Projects). Set a default in Watchlists to skip this next
          time.
        </p>
        {projects.length === 0 ? (
          <p className="mt-4 text-sm text-[var(--o-text-secondary)]">
            No projects yet.{" "}
            <Link to="/projects" className="text-[var(--o-accent)]">
              Create one
            </Link>
            .
          </p>
        ) : (
          <select
            className="o-input mt-4 w-full text-sm"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="o-btn-ghost text-sm" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="o-btn-primary text-sm"
            disabled={!selected || busy}
            onClick={() => onPick(selected)}
          >
            {busy ? "Opening…" : "Start Focus"}
          </button>
        </div>
      </div>
    </div>
  );
}
