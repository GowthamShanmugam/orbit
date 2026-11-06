import {
  listCoachMeetings,
  type CoachCalendarMeetingOption,
  type CoachJiraItem,
  type CoachMeetingItem,
  type CoachReminderPrefs,
  type CoachRepoItem,
  type CoachWatchlists,
} from "@/api/coach";
import { listProjects } from "@/api/projects";
import type { Project } from "@/types";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, ChevronRight, Plus, Trash2, X } from "lucide-react";
import { Link } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

type Tab = "jira" | "meetings" | "repos" | "reminders";
type MeetingFilter = "all" | "today";

function newId(): string {
  return crypto.randomUUID();
}

/** True when the event starts on the user's local calendar day. */
function isTodayMeeting(m: { start?: string; is_today?: boolean }): boolean {
  if (m.start) {
    const d = new Date(m.start);
    if (!Number.isNaN(d.getTime())) {
      const now = new Date();
      return (
        d.getFullYear() === now.getFullYear() &&
        d.getMonth() === now.getMonth() &&
        d.getDate() === now.getDate()
      );
    }
  }
  return m.is_today === true;
}

function formatMeetingWhen(m: { start?: string; time_local?: string; label?: string }): string {
  if (m.start) {
    const d = new Date(m.start);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    }
  }
  return m.time_local || m.label || "";
}

interface Props {
  open: boolean;
  onClose: () => void;
  watchlists: CoachWatchlists;
  reminderPrefs: CoachReminderPrefs;
  onSave: (next: {
    watchlists: CoachWatchlists;
    reminder_prefs: CoachReminderPrefs;
  }) => Promise<void>;
}

export default function WatchlistsDrawer({
  open,
  onClose,
  watchlists,
  reminderPrefs,
  onSave,
}: Props) {
  const [tab, setTab] = useState<Tab>("jira");
  const [jira, setJira] = useState<CoachJiraItem[]>([]);
  const [meetings, setMeetings] = useState<CoachMeetingItem[]>([]);
  const [repos, setRepos] = useState<CoachRepoItem[]>([]);
  const [prefs, setPrefs] = useState<CoachReminderPrefs>(reminderPrefs);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState<Record<string, boolean>>({});
  const [jiraKeyDraft, setJiraKeyDraft] = useState("");
  const [meetingFilter, setMeetingFilter] = useState<MeetingFilter>("all");
  const [meetingSearch, setMeetingSearch] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
    enabled: open,
  });
  const projects: Project[] = projectsQuery.data ?? [];

  const meetingOptionsQuery = useQuery({
    queryKey: ["coach", "meetings"],
    queryFn: listCoachMeetings,
    enabled: open && tab === "meetings",
    staleTime: 2 * 60_000,
  });
  const meetingOptions = meetingOptionsQuery.data;

  const watchedKeys = useMemo(
    () => new Set(jira.map((j) => j.project_key).filter(Boolean)),
    [jira],
  );

  const watchedMeetingIds = useMemo(
    () =>
      new Set(
        meetings
          .map((m) => m.calendar_event_id)
          .filter((id): id is string => Boolean(id)),
      ),
    [meetings],
  );

  const filteredCalendarMeetings = useMemo(() => {
    const q = meetingSearch.trim().toLowerCase();
    return (meetingOptions?.meetings ?? []).filter((m) => {
      // Today lists every meeting that starts today, including ones already watched.
      if (meetingFilter !== "today" && watchedMeetingIds.has(m.calendar_event_id)) return false;
      if (meetingFilter === "today" && !isTodayMeeting(m)) return false;
      if (q && !`${m.title} ${m.label}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [meetingOptions?.meetings, watchedMeetingIds, meetingFilter, meetingSearch]);

  const todayMeetingCount = useMemo(
    () => (meetingOptions?.meetings ?? []).filter((m) => isTodayMeeting(m)).length,
    [meetingOptions?.meetings],
  );

  useEffect(() => {
    if (!open) return;
    setJira(watchlists.jira.map((x) => ({ ...x })));
    setMeetings(watchlists.meetings.map((x) => ({ ...x })));
    setRepos(watchlists.repos.map((x) => ({ ...x })));
    setPrefs({
      enabled: reminderPrefs.enabled ?? true,
      standup_minutes_before: reminderPrefs.standup_minutes_before ?? 15,
      default_orbit_project_id: reminderPrefs.default_orbit_project_id ?? null,
    });
    setError(null);
    setScheduleOpen({});
    setJiraKeyDraft("");
    setMeetingFilter("all");
    setMeetingSearch("");
  }, [open, watchlists, reminderPrefs]);

  if (!open) return null;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const cleanedJira = jira
        .filter((j) => j.project_key.trim())
        .map((j) => ({
          ...j,
          project_key: j.project_key.trim().toUpperCase(),
          orbit_project_id: null,
        }));
      const cleanedRepos = repos
        .filter((r) => r.owner.trim() && r.repo.trim())
        .map((r) => ({
          ...r,
          owner: r.owner.trim(),
          repo: r.repo.trim(),
          orbit_project_id: null,
        }));
      const cleanedMeetings = meetings
        .filter((m) => m.title.trim())
        .map((m) => ({
          ...m,
          title: m.title.trim(),
          days_of_week: m.days_of_week?.length ? m.days_of_week : [0, 1, 2, 3, 4],
          time_local: m.time_local || "09:30",
        }));
      await onSave({
        watchlists: { jira: cleanedJira, meetings: cleanedMeetings, repos: cleanedRepos },
        reminder_prefs: prefs,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const addJiraFromKey = (raw: string) => {
    const k = raw.trim().toUpperCase();
    if (!k || watchedKeys.has(k)) return;
    setJira([
      ...jira,
      {
        id: newId(),
        project_key: k,
        label: k,
        orbit_project_id: null,
      },
    ]);
    setJiraKeyDraft("");
  };

  const addMeetingFromCalendar = (opt: CoachCalendarMeetingOption) => {
    if (watchedMeetingIds.has(opt.calendar_event_id)) return;
    setMeetings([
      ...meetings,
      {
        id: newId(),
        title: opt.title,
        calendar_event_id: opt.calendar_event_id,
        time_local: opt.time_local,
        days_of_week: opt.days_of_week?.length ? opt.days_of_week : [0, 1, 2, 3, 4],
        notes_url: opt.notes_url ?? null,
        notes_doc_id: opt.notes_doc_id ?? null,
      },
    ]);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" role="dialog" aria-modal>
      <button type="button" className="flex-1 cursor-default" aria-label="Close" onClick={onClose} />
      <div className="flex h-full w-full max-w-lg flex-col border-l border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-xl">
        <div className="border-b border-[var(--o-border)] px-4 py-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--o-text)]">What should Today watch?</h2>
            <button type="button" className="o-btn-icon h-8 w-8" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-[var(--o-text-tertiary)]">
            Pick Jira boards, standup meetings, and repos once. Today uses only these every day.
          </p>
        </div>

        {/* One shared Focus home — not repeated on each item */}
        <div className="border-b border-[var(--o-border)] bg-[var(--o-bg-subtle)]/50 px-4 py-3">
          <label className="block text-xs font-medium text-[var(--o-text)]">
            Open Focus sessions in
          </label>
          <p className="mt-0.5 text-[11px] text-[var(--o-text-tertiary)]">
            This is your <strong className="font-medium text-[var(--o-text-secondary)]">Orbit</strong>{" "}
            workspace (under Projects) — not a Jira project. Focus always opens a session here.
          </p>
          <select
            className="o-input mt-2 w-full text-sm"
            value={prefs.default_orbit_project_id ?? ""}
            onChange={(e) =>
              setPrefs({
                ...prefs,
                default_orbit_project_id: e.target.value || null,
              })
            }
          >
            <option value="">Choose an Orbit project…</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {projects.length === 0 && (
            <p className="mt-1 text-[11px] text-[var(--o-text-tertiary)]">
              No Orbit projects yet.{" "}
              <Link to="/projects" className="text-[var(--o-accent)]" onClick={onClose}>
                Create one
              </Link>
              .
            </p>
          )}
        </div>

        <div className="flex gap-1 border-b border-[var(--o-border)] px-3 pt-2">
          {(
            [
              ["jira", "Jira"],
              ["meetings", "Meetings"],
              ["repos", "Repos"],
              ["reminders", "Reminders"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={clsx(
                "rounded-t-md px-3 py-2 text-xs font-medium",
                tab === id
                  ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                  : "text-[var(--o-text-secondary)] hover:text-[var(--o-text)]",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {tab === "jira" && (
            <div className="space-y-4">
              <p className="text-xs leading-relaxed text-[var(--o-text-tertiary)]">
                Type the <strong className="font-medium text-[var(--o-text-secondary)]">Jira project key</strong>{" "}
                you work in (for example <code className="text-[var(--o-text-secondary)]">DATA</code>).
                Today shows your open tickets from these keys only.
              </p>

              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--o-text)]">
                  Jira project key
                </label>
                <div className="flex gap-2">
                  <input
                    className="o-input flex-1 text-sm uppercase"
                    placeholder="e.g. DATA"
                    value={jiraKeyDraft}
                    onChange={(e) => setJiraKeyDraft(e.target.value.toUpperCase())}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addJiraFromKey(jiraKeyDraft);
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="o-btn-primary shrink-0 text-sm"
                    disabled={!jiraKeyDraft.trim()}
                    onClick={() => addJiraFromKey(jiraKeyDraft)}
                  >
                    Add
                  </button>
                </div>
              </div>

              {jira.length === 0 ? (
                <p className="text-sm text-[var(--o-text-tertiary)]">No Jira projects watched yet.</p>
              ) : (
                <ul className="space-y-2">
                  {jira.map((item) => (
                    <li
                      key={item.id}
                      className="flex items-center justify-between gap-2 rounded-lg border border-[var(--o-border)] px-3 py-2"
                    >
                      <p className="truncate text-sm font-medium text-[var(--o-text)]">
                        {item.project_key}
                      </p>
                      <button
                        type="button"
                        className="o-btn-icon text-red-400"
                        onClick={() => setJira(jira.filter((j) => j.id !== item.id))}
                        aria-label={`Remove ${item.project_key}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {tab === "meetings" && (
            <div className="space-y-4">
              <p className="text-xs leading-relaxed text-[var(--o-text-tertiary)]">
                Watch a meeting series once. Orbit drafts only on days that series actually appears
                on your calendar (daily, weekly, biweekly, or moved) — not every weekday.
              </p>

              {meetingOptionsQuery.isLoading ? (
                <p className="text-sm text-[var(--o-text-secondary)]">Loading calendar…</p>
              ) : meetingOptions?.error && (meetingOptions.meetings?.length ?? 0) === 0 ? (
                <div className="rounded-lg border border-dashed border-[var(--o-border)] p-3 text-sm text-[var(--o-text-secondary)]">
                  <p>{meetingOptions.error}</p>
                  {(meetingOptions.needs_reauth || !meetingOptions.connected) && (
                    <Link
                      to="/integrations"
                      className="mt-2 inline-flex text-[var(--o-accent)]"
                      onClick={onClose}
                    >
                      Open Integrations
                    </Link>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="block text-xs font-medium text-[var(--o-text)]">
                    Add a meeting from calendar
                  </label>
                  <div className="flex flex-wrap gap-1">
                    {(
                      [
                        ["all", "All"],
                        ["today", "Today"],
                      ] as const
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setMeetingFilter(id)}
                        className={clsx(
                          "rounded-md px-2.5 py-1 text-[11px] font-medium",
                          meetingFilter === id
                            ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                            : "bg-[var(--o-bg-subtle)] text-[var(--o-text-tertiary)] hover:text-[var(--o-text)]",
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <input
                    className="o-input w-full text-sm"
                    placeholder="Search by name…"
                    value={meetingSearch}
                    onChange={(e) => setMeetingSearch(e.target.value)}
                  />
                  {(meetingOptions?.meetings?.length ?? 0) === 0 ? (
                    <p className="text-[11px] text-[var(--o-text-tertiary)]">
                      No timed events in the next 14 days on your primary calendar.
                    </p>
                  ) : filteredCalendarMeetings.length === 0 ? (
                    <p className="text-[11px] text-[var(--o-text-tertiary)]">
                      {meetingFilter === "today"
                        ? "No meetings on your calendar today."
                        : meetingSearch.trim()
                          ? `No matches for “${meetingSearch.trim()}”.`
                          : "No matches."}
                    </p>
                  ) : (
                    <ul className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-[var(--o-border)] p-1">
                      {meetingFilter === "today" && (
                        <li className="px-2 py-1 text-[11px] text-[var(--o-text-tertiary)]">
                          {todayMeetingCount} meeting{todayMeetingCount === 1 ? "" : "s"} today
                        </li>
                      )}
                      {filteredCalendarMeetings.map((m) => {
                        const watching = watchedMeetingIds.has(m.calendar_event_id);
                        return (
                          <li key={`${m.calendar_event_id}-${m.start}`}>
                            <button
                              type="button"
                              disabled={watching}
                              className="flex w-full items-start justify-between gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-[var(--o-bg-subtle)] disabled:cursor-default disabled:hover:bg-transparent"
                              onClick={() => addMeetingFromCalendar(m)}
                            >
                              <span className="min-w-0">
                                <span className="block truncate font-medium text-[var(--o-text)]">
                                  {m.title}
                                </span>
                                <span className="block text-[11px] text-[var(--o-text-tertiary)]">
                                  {formatMeetingWhen(m)}
                                  {m.notes_url ? " · notes" : ""}
                                </span>
                              </span>
                              <span
                                className={clsx(
                                  "shrink-0 text-[11px]",
                                  watching
                                    ? "text-[var(--o-text-tertiary)]"
                                    : "text-[var(--o-accent)]",
                                )}
                              >
                                {watching ? "Watching" : "Add"}
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              )}

              {meetings.length === 0 ? (
                <p className="text-sm text-[var(--o-text-tertiary)]">No meetings watched yet.</p>
              ) : (
                <ul className="space-y-2">
                  {meetings.map((item, idx) => {
                    const advanced = scheduleOpen[item.id] ?? false;
                    const fromCalendar = Boolean(item.calendar_event_id);
                    const dayBits = (item.days_of_week ?? [0, 1, 2, 3, 4])
                      .map((d) => DAY_LABELS[d])
                      .join(" ");
                    return (
                      <li
                        key={item.id}
                        className="rounded-lg border border-[var(--o-border)] px-3 py-2"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium text-[var(--o-text)]">
                              {item.title}
                            </p>
                            <p className="text-[11px] text-[var(--o-text-tertiary)]">
                              {fromCalendar
                                ? "Follows your calendar"
                                : `${item.time_local || "—"} · ${dayBits || "weekdays"}`}
                              {item.notes_url ? " · notes linked" : ""}
                            </p>
                          </div>
                          <button
                            type="button"
                            className="o-btn-icon text-red-400"
                            onClick={() => setMeetings(meetings.filter((_, i) => i !== idx))}
                            aria-label="Remove"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                        <button
                          type="button"
                          className="mt-1 inline-flex items-center gap-1 text-[11px] text-[var(--o-text-tertiary)] hover:text-[var(--o-text)]"
                          onClick={() =>
                            setScheduleOpen((s) => ({ ...s, [item.id]: !advanced }))
                          }
                        >
                          {advanced ? (
                            <ChevronDown className="h-3 w-3" />
                          ) : (
                            <ChevronRight className="h-3 w-3" />
                          )}
                          {fromCalendar ? "Notes URL" : "Schedule / notes"}
                        </button>
                        {advanced && (
                          <div className="mt-2 space-y-2 rounded-md bg-[var(--o-bg-subtle)] p-2">
                            <input
                              className="o-input w-full text-sm"
                              placeholder="Notes / template URL"
                              value={item.notes_url ?? ""}
                              onChange={(e) => {
                                const next = [...meetings];
                                next[idx] = { ...item, notes_url: e.target.value || null };
                                setMeetings(next);
                              }}
                            />
                            {!fromCalendar && (
                              <>
                                <p className="text-[11px] text-[var(--o-text-tertiary)]">
                                  Only for manual watches (no calendar link).
                                </p>
                                <input
                                  className="o-input w-28 text-sm"
                                  placeholder="09:30"
                                  value={item.time_local ?? ""}
                                  onChange={(e) => {
                                    const next = [...meetings];
                                    next[idx] = {
                                      ...item,
                                      time_local: e.target.value || null,
                                    };
                                    setMeetings(next);
                                  }}
                                />
                                <div className="flex flex-wrap gap-1">
                                  {DAY_LABELS.map((d, dayIdx) => {
                                    const active = (
                                      item.days_of_week ?? [0, 1, 2, 3, 4]
                                    ).includes(dayIdx);
                                    return (
                                      <button
                                        key={d}
                                        type="button"
                                        className={clsx(
                                          "rounded px-1.5 py-0.5 text-[10px] font-medium",
                                          active
                                            ? "bg-[var(--o-accent-muted)] text-[var(--o-accent)]"
                                            : "bg-[var(--o-bg-raised)] text-[var(--o-text-tertiary)]",
                                        )}
                                        onClick={() => {
                                          const cur = new Set(
                                            item.days_of_week ?? [0, 1, 2, 3, 4],
                                          );
                                          if (cur.has(dayIdx)) cur.delete(dayIdx);
                                          else cur.add(dayIdx);
                                          const next = [...meetings];
                                          next[idx] = {
                                            ...item,
                                            days_of_week: [...cur].sort(),
                                          };
                                          setMeetings(next);
                                        }}
                                      >
                                        {d}
                                      </button>
                                    );
                                  })}
                                </div>
                              </>
                            )}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}

              <button
                type="button"
                className="inline-flex items-center gap-1.5 text-sm text-[var(--o-text-tertiary)] hover:text-[var(--o-accent)]"
                onClick={() =>
                  setMeetings([
                    ...meetings,
                    {
                      id: newId(),
                      title: "Custom meeting",
                      days_of_week: [0, 1, 2, 3, 4],
                      time_local: "09:30",
                    },
                  ])
                }
              >
                <Plus className="h-3.5 w-3.5" /> Add manually (no calendar)
              </button>
            </div>
          )}

          {tab === "repos" && (
            <div className="space-y-4">
              <p className="text-xs leading-relaxed text-[var(--o-text-tertiary)]">
                Watch GitHub/GitLab repos for <strong className="font-medium text-[var(--o-text-secondary)]">your MRs</strong>{" "}
                and <strong className="font-medium text-[var(--o-text-secondary)]">reviews waiting on you</strong>.
                Focus uses the same Orbit project chosen above.
              </p>
              {repos.map((item, idx) => (
                <div
                  key={item.id}
                  className="space-y-2 rounded-lg border border-[var(--o-border)] p-3"
                >
                  <div className="flex gap-2">
                    <select
                      className="o-input w-28 text-sm"
                      value={item.provider}
                      onChange={(e) => {
                        const next = [...repos];
                        next[idx] = {
                          ...item,
                          provider: e.target.value as "github" | "gitlab",
                        };
                        setRepos(next);
                      }}
                    >
                      <option value="github">GitHub</option>
                      <option value="gitlab">GitLab</option>
                    </select>
                    <button
                      type="button"
                      className="o-btn-icon text-red-400"
                      onClick={() => setRepos(repos.filter((_, i) => i !== idx))}
                      aria-label="Remove"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="flex gap-2">
                    <input
                      className="o-input flex-1 text-sm"
                      placeholder="owner / group"
                      value={item.owner}
                      onChange={(e) => {
                        const next = [...repos];
                        next[idx] = { ...item, owner: e.target.value };
                        setRepos(next);
                      }}
                    />
                    <input
                      className="o-input flex-1 text-sm"
                      placeholder="repository"
                      value={item.repo}
                      onChange={(e) => {
                        const next = [...repos];
                        next[idx] = { ...item, repo: e.target.value };
                        setRepos(next);
                      }}
                    />
                  </div>
                </div>
              ))}
              <button
                type="button"
                className="inline-flex items-center gap-1.5 text-sm text-[var(--o-accent)]"
                onClick={() =>
                  setRepos([
                    ...repos,
                    {
                      id: newId(),
                      provider: "github",
                      owner: "",
                      repo: "",
                      orbit_project_id: null,
                    },
                  ])
                }
              >
                <Plus className="h-3.5 w-3.5" /> Add repo to watch
              </button>
            </div>
          )}

          {tab === "reminders" && (
            <div className="space-y-4">
              <p className="text-xs text-[var(--o-text-tertiary)]">
                Light in-app nudges before a watched standup. No email or Slack spam.
              </p>
              <label className="flex items-center gap-2 text-sm text-[var(--o-text)]">
                <input
                  type="checkbox"
                  checked={prefs.enabled}
                  onChange={(e) => setPrefs({ ...prefs, enabled: e.target.checked })}
                />
                Remind me before standup
              </label>
              <label className="block text-sm text-[var(--o-text-secondary)]">
                Minutes before meeting
                <input
                  type="number"
                  min={0}
                  max={120}
                  className="o-input mt-1 w-28 text-sm"
                  value={prefs.standup_minutes_before}
                  onChange={(e) =>
                    setPrefs({
                      ...prefs,
                      standup_minutes_before: Number(e.target.value) || 0,
                    })
                  }
                />
              </label>
            </div>
          )}
        </div>

        <div className="border-t border-[var(--o-border)] p-4">
          {error && (
            <p className="mb-2 text-sm text-red-400" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="o-btn-ghost text-sm" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="o-btn-primary text-sm"
              disabled={saving}
              onClick={() => void save()}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
