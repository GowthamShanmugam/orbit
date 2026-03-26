import { apiClient } from "./client";

export interface RepoInfo {
  id: string;
  name: string;
  url: string | null;
  cloned: boolean;
}

export interface FileEntry {
  name: string;
  type: "file" | "dir";
  size: number | null;
  path: string;
}

export interface FileContent {
  path: string;
  content: string;
  language: string;
  size: number;
  total_lines: number;
}

export async function listRepos(projectId: string): Promise<RepoInfo[]> {
  const { data } = await apiClient.get<RepoInfo[]>(
    `/projects/${projectId}/repos`
  );
  return data;
}

export async function listDirectory(
  projectId: string,
  repoId: string,
  path = ""
): Promise<FileEntry[]> {
  const { data } = await apiClient.get<FileEntry[]>(
    `/projects/${projectId}/repos/${repoId}/tree`,
    { params: { path } }
  );
  return data;
}

export async function readFile(
  projectId: string,
  repoId: string,
  path: string
): Promise<FileContent> {
  const { data } = await apiClient.get<FileContent>(
    `/projects/${projectId}/repos/${repoId}/file`,
    { params: { path } }
  );
  return data;
}
