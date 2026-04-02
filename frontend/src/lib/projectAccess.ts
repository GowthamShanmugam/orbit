import type { Project, ProjectUserAccess } from "@/types";

/** Normalize API field; missing value means full access (pre–share-enforcement clients). */
export function effectiveProjectAccess(
  project: Pick<Project, "current_user_access"> | null | undefined,
): ProjectUserAccess {
  return project?.current_user_access ?? "admin";
}

export function canWriteProject(access: ProjectUserAccess): boolean {
  return access === "write" || access === "admin";
}

export function canAdminProject(access: ProjectUserAccess): boolean {
  return access === "admin";
}
