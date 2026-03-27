const STORAGE_KEY = "orbit_recent_sessions";
const MAX_ITEMS = 10;

export interface RecentSessionEntry {
  projectId: string;
  sessionId: string;
  sessionTitle: string;
  projectName: string;
  openedAt: number;
}

function parseStored(raw: string | null): RecentSessionEntry[] {
  if (!raw) return [];
  try {
    const data = JSON.parse(raw) as unknown;
    if (!Array.isArray(data)) return [];
    const out: RecentSessionEntry[] = [];
    for (const row of data) {
      if (
        row &&
        typeof row === "object" &&
        typeof (row as RecentSessionEntry).projectId === "string" &&
        typeof (row as RecentSessionEntry).sessionId === "string" &&
        typeof (row as RecentSessionEntry).sessionTitle === "string" &&
        typeof (row as RecentSessionEntry).projectName === "string" &&
        typeof (row as RecentSessionEntry).openedAt === "number"
      ) {
        out.push(row as RecentSessionEntry);
      }
    }
    return out;
  } catch {
    return [];
  }
}

export function readRecentSessions(): RecentSessionEntry[] {
  try {
    return parseStored(localStorage.getItem(STORAGE_KEY));
  } catch {
    return [];
  }
}

function writeRecentSessions(entries: RecentSessionEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ITEMS)));
  } catch {
    /* quota / private mode */
  }
}

export function recordRecentSession(input: {
  projectId: string;
  sessionId: string;
  sessionTitle: string;
  projectName: string;
}): void {
  const openedAt = Date.now();
  const prev = readRecentSessions().filter(
    (e) =>
      !(e.projectId === input.projectId && e.sessionId === input.sessionId),
  );
  const next: RecentSessionEntry[] = [
    {
      projectId: input.projectId,
      sessionId: input.sessionId,
      sessionTitle: input.sessionTitle.trim() || "Session",
      projectName: input.projectName.trim() || "Project",
      openedAt,
    },
    ...prev,
  ];
  writeRecentSessions(next);
}

export function removeRecentSession(projectId: string, sessionId: string): void {
  const next = readRecentSessions().filter(
    (e) => !(e.projectId === projectId && e.sessionId === sessionId),
  );
  writeRecentSessions(next);
}

export function removeRecentSessionsForProject(projectId: string): void {
  const next = readRecentSessions().filter((e) => e.projectId !== projectId);
  writeRecentSessions(next);
}
