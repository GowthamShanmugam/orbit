import {
  createProjectShare,
  deleteProjectShare,
  listProjectShares,
  patchProjectShare,
} from "@/api/projects";
import type { ProjectShare, ProjectShareRole } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Loader2, Trash2, UserPlus } from "lucide-react";
import { useState } from "react";

const ROLES: { value: ProjectShareRole; label: string }[] = [
  { value: "view", label: "View" },
  { value: "edit", label: "Edit" },
  { value: "admin", label: "Admin" },
];

type Props = { projectId: string; canManageShares?: boolean };

export default function ProjectSharing({
  projectId,
  canManageShares = true,
}: Props) {
  const queryClient = useQueryClient();
  const [grantOpen, setGrantOpen] = useState(false);
  const [subjectKind, setSubjectKind] = useState<"user" | "group">("user");
  const [userIdentifier, setUserIdentifier] = useState("");
  const [groupName, setGroupName] = useState("");
  const [newRole, setNewRole] = useState<ProjectShareRole>("view");
  const [formError, setFormError] = useState<string | null>(null);

  const sharesQuery = useQuery({
    queryKey: ["project-shares", projectId],
    queryFn: () => listProjectShares(projectId),
    enabled: Boolean(projectId),
  });

  const grantMut = useMutation({
    mutationFn: () =>
      createProjectShare(projectId, {
        subject_type: subjectKind,
        role: newRole,
        user_identifier:
          subjectKind === "user" ? userIdentifier.trim() : undefined,
        group_name: subjectKind === "group" ? groupName.trim() : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-shares", projectId] });
      setGrantOpen(false);
      setUserIdentifier("");
      setGroupName("");
      setFormError(null);
      setNewRole("view");
    },
    onError: (e: unknown) => {
      const msg =
        e &&
        typeof e === "object" &&
        "response" in e &&
        e.response &&
        typeof e.response === "object" &&
        "data" in e.response &&
        e.response.data &&
        typeof e.response.data === "object" &&
        "detail" in e.response.data
          ? String((e.response.data as { detail: unknown }).detail)
          : "Could not grant access";
      setFormError(msg);
    },
  });

  const patchMut = useMutation({
    mutationFn: ({ shareId, role }: { shareId: string; role: ProjectShareRole }) =>
      patchProjectShare(projectId, shareId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-shares", projectId] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (shareId: string) => deleteProjectShare(projectId, shareId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-shares", projectId] });
    },
  });

  const shares = sharesQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
          Sharing
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-[var(--o-text-secondary)]">
          Users and groups with access to this workspace and their roles. When
          at least one entry exists, only listed users (and organization admins)
          can open this project; organization-wide access is no longer implicit.
        </p>
      </div>

      {canManageShares && (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => {
              setGrantOpen(true);
              setFormError(null);
            }}
            className="o-btn-primary inline-flex items-center gap-2 px-4 py-2 text-sm"
          >
            <UserPlus className="h-4 w-4" />
            Grant permission
          </button>
        </div>
      )}

      {sharesQuery.isLoading ? (
        <div className="flex justify-center py-12 text-[var(--o-text-secondary)]">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : shares.length === 0 ? (
        <div className="o-empty rounded-lg border border-dashed border-[var(--o-border)] p-8 text-center text-sm text-[var(--o-text-secondary)]">
          No explicit shares yet. All members of this project&apos;s organization
          can access this project. Add a user or group to restrict access.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--o-border)]">
          <table className="w-full min-w-[520px] text-left text-sm">
            <thead>
              <tr className="border-b border-[var(--o-border)] bg-[var(--o-bg-elevated)] text-xs uppercase tracking-wide text-[var(--o-text-tertiary)]">
                <th className="px-4 py-3 font-medium">Subject</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Role</th>
                {canManageShares && (
                  <th className="px-4 py-3 font-medium text-right">Actions</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--o-border)]">
              {shares.map((row: ProjectShare) => (
                <tr key={row.id} className="hover:bg-[var(--o-bg-elevated)]/50">
                  <td className="px-4 py-3 font-medium text-[var(--o-text)]">
                    {row.display_name}
                  </td>
                  <td className="px-4 py-3 capitalize text-[var(--o-text-secondary)]">
                    {row.subject_type}
                  </td>
                  <td className="px-4 py-3">
                    {canManageShares ? (
                      <select
                        value={row.role}
                        disabled={patchMut.isPending}
                        onChange={(e) => {
                          const role = e.target.value as ProjectShareRole;
                          patchMut.mutate({ shareId: row.id, role });
                        }}
                        className="o-input rounded-md px-2 py-1.5 text-sm"
                      >
                        {ROLES.map((r) => (
                          <option key={r.value} value={r.value}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="capitalize text-[var(--o-text-secondary)]">
                        {row.role}
                      </span>
                    )}
                  </td>
                  {canManageShares && (
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => deleteMut.mutate(row.id)}
                        disabled={deleteMut.isPending}
                        className="inline-flex rounded-lg p-1.5 text-[var(--o-text-tertiary)] transition-colors hover:bg-[var(--o-danger)]/10 hover:text-[var(--o-danger)]"
                        title="Remove access"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {grantOpen && (
        <div
          className="o-modal-backdrop fixed inset-0 z-[100] flex items-center justify-center p-4"
          onClick={() => !grantMut.isPending && setGrantOpen(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="grant-share-title"
            className="o-modal w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-b border-[var(--o-border)] px-6 py-5">
              <h2
                id="grant-share-title"
                className="text-lg font-semibold text-[var(--o-text)]"
              >
                Grant permission
              </h2>
              <p className="mt-1 text-sm text-[var(--o-text-secondary)]">
                Add a user or group to this workspace with a role. Users must
                already belong to this project&apos;s organization.
              </p>
            </div>
            <form
              className="space-y-4 p-6"
              onSubmit={(e) => {
                e.preventDefault();
                setFormError(null);
                if (subjectKind === "user" && !userIdentifier.trim()) {
                  setFormError("Enter a user name or email.");
                  return;
                }
                if (subjectKind === "group" && !groupName.trim()) {
                  setFormError("Enter a group name.");
                  return;
                }
                grantMut.mutate();
              }}
            >
              <div className="space-y-2">
                <span className="text-xs font-medium text-[var(--o-text-secondary)]">
                  Subject type
                </span>
                <div className="flex gap-4">
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="subj"
                      checked={subjectKind === "group"}
                      onChange={() => setSubjectKind("group")}
                    />
                    Group
                  </label>
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="subj"
                      checked={subjectKind === "user"}
                      onChange={() => setSubjectKind("user")}
                    />
                    User
                  </label>
                </div>
              </div>

              {subjectKind === "group" ? (
                <div>
                  <label
                    htmlFor="share-group"
                    className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
                  >
                    Group name
                  </label>
                  <input
                    id="share-group"
                    value={groupName}
                    onChange={(e) => setGroupName(e.target.value)}
                    className="o-input w-full px-3 py-2.5 text-sm"
                    placeholder="Enter group name"
                  />
                  <p className="mt-1.5 text-xs text-[var(--o-text-tertiary)]">
                    Stored for reference; OpenShift/OIDC group matching can be
                    wired later.
                  </p>
                </div>
              ) : (
                <div>
                  <label
                    htmlFor="share-user"
                    className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
                  >
                    User
                  </label>
                  <input
                    id="share-user"
                    value={userIdentifier}
                    onChange={(e) => setUserIdentifier(e.target.value)}
                    className="o-input w-full px-3 py-2.5 text-sm"
                    placeholder="Email or username (e.g. gowtham)"
                  />
                </div>
              )}

              <div>
                <label
                  htmlFor="share-role"
                  className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]"
                >
                  Permission
                </label>
                <select
                  id="share-role"
                  value={newRole}
                  onChange={(e) =>
                    setNewRole(e.target.value as ProjectShareRole)
                  }
                  className="o-input w-full px-3 py-2.5 text-sm"
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>

              {formError && (
                <p className="text-sm text-[var(--o-danger)]">{formError}</p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={grantMut.isPending}
                  onClick={() => setGrantOpen(false)}
                  className="o-btn-ghost rounded-lg px-4 py-2 text-sm"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={grantMut.isPending}
                  className={clsx(
                    "o-btn-primary inline-flex items-center gap-2 px-5 py-2 text-sm",
                    grantMut.isPending && "opacity-60",
                  )}
                >
                  {grantMut.isPending && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  Add
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
