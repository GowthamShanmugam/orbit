import type { FileContent, FileEntry } from "./files";
import { apiClient, getStoredToken } from "./client";

export type { FileEntry, FileContent };

export async function listArtifactDirectory(
  projectId: string,
  sessionId: string,
  path = "",
): Promise<FileEntry[]> {
  const { data } = await apiClient.get<FileEntry[]>(
    `/projects/${projectId}/sessions/${sessionId}/artifacts/tree`,
    { params: { path } },
  );
  return data;
}

export async function readArtifactFile(
  projectId: string,
  sessionId: string,
  path: string,
): Promise<FileContent> {
  const { data } = await apiClient.get<FileContent>(
    `/projects/${projectId}/sessions/${sessionId}/artifacts/file`,
    { params: { path } },
  );
  return data;
}

/** Browser download with Authorization header (not usable as plain href). */
export async function downloadArtifactFile(
  projectId: string,
  sessionId: string,
  path: string,
): Promise<void> {
  const baseUrl = apiClient.defaults.baseURL ?? "/api";
  const token = getStoredToken();
  const url = `${baseUrl}/projects/${projectId}/sessions/${sessionId}/artifacts/download?path=${encodeURIComponent(path)}`;
  const res = await fetch(url, {
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error(`Download failed (${res.status})`);
  }
  const blob = await res.blob();
  const name = path.split("/").pop() || "download";
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = name;
  a.click();
  URL.revokeObjectURL(objectUrl);
}
