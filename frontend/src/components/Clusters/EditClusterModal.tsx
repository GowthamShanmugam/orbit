import { updateCluster } from "@/api/clusters";
import type { ClusterAuthMethod, ProjectCluster, UpdateClusterInput } from "@/types";
import clsx from "clsx";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Eye, EyeOff, Loader2, Shield, X, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

interface Props {
  projectId: string;
  cluster: ProjectCluster;
  onClose: () => void;
}

export default function EditClusterModal({ projectId, cluster, onClose }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState(cluster.name);
  const [authMethod] = useState<ClusterAuthMethod>(cluster.auth_method);
  const [apiServerUrl, setApiServerUrl] = useState(
    cluster.api_server_url ?? "",
  );
  const [token, setToken] = useState("");
  const [kubeconfig, setKubeconfig] = useState("");
  const [namespacesRaw, setNamespacesRaw] = useState(
    (cluster.namespace_filter ?? []).join(", "),
  );
  const [verifySsl, setVerifySsl] = useState(true);
  const [showToken, setShowToken] = useState(false);
  const [showKubeconfig, setShowKubeconfig] = useState(false);
  const [result, setResult] = useState<ProjectCluster | null>(null);

  useEffect(() => {
    setName(cluster.name);
    setApiServerUrl(cluster.api_server_url ?? "");
    setNamespacesRaw((cluster.namespace_filter ?? []).join(", "));
    setToken("");
    setKubeconfig("");
  }, [cluster]);

  const updateMut = useMutation({
    mutationFn: () => {
      const namespaceFilter = namespacesRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

      const body: UpdateClusterInput = {
        name: name.trim(),
        namespace_filter: namespaceFilter.length ? namespaceFilter : null,
      };

      if (authMethod === "token") {
        body.api_server_url = apiServerUrl.trim() || null;
      }

      const newToken = token.trim();
      const newKube = kubeconfig.trim();
      if (authMethod === "token" && newToken) {
        body.credentials = {
          token: newToken,
          api_server_url: apiServerUrl.trim(),
          verify_ssl: verifySsl,
        };
      } else if (authMethod === "kubeconfig" && newKube) {
        body.credentials = { kubeconfig: newKube, verify_ssl: verifySsl };
      }

      return updateCluster(projectId, cluster.id, body);
    },
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["clusters", projectId] });
      setResult(updated);
    },
  });

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center o-modal-backdrop p-4"
      onClick={() => !updateMut.isPending && onClose()}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-lg o-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--o-border)] px-5 py-4">
          <h2 className="text-lg font-semibold text-[var(--o-text)]">
            Edit cluster
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--o-text-secondary)] hover:text-[var(--o-text)]"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {result ? (
          <div className="space-y-4 p-5">
            <div
              className={clsx(
                "flex items-start gap-3 rounded-lg border p-4",
                result.status === "connected"
                  ? "border-[var(--o-green-bg)]/30 bg-[var(--o-green-bg)]/10"
                  : "border-[var(--o-danger)]/30 bg-[var(--o-danger)]/10",
              )}
            >
              {result.status === "connected" ? (
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[var(--o-green)]" />
              ) : (
                <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-[var(--o-danger)]" />
              )}
              <div className="min-w-0">
                <p
                  className={clsx(
                    "text-sm font-medium",
                    result.status === "connected"
                      ? "text-[var(--o-green)]"
                      : "text-[var(--o-danger)]",
                  )}
                >
                  {result.status === "connected"
                    ? `Cluster "${result.name}" updated and reachable`
                    : `Cluster "${result.name}" saved but connection check failed`}
                </p>
                {result.status_message && (
                  <p className="mt-1 break-words text-xs text-[var(--o-text-secondary)]">
                    {result.status_message}
                  </p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 rounded-md bg-[var(--o-bg-subtle)]/60 px-3 py-2 text-[11px] text-[var(--o-text-secondary)]">
              <Shield className="h-3.5 w-3.5 shrink-0 text-[var(--o-green)]" />
              Credentials encrypted with AES-256-GCM — never stored in plain text
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="o-btn-success px-4 py-2 text-sm"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form
            className="space-y-4 p-5"
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim() || updateMut.isPending) return;
              updateMut.mutate();
            }}
          >
            <p className="text-xs text-[var(--o-text-secondary)]">
              Update name, API URL, namespaces, or paste a{" "}
              <strong className="text-[var(--o-text)]">new token or kubeconfig</strong>{" "}
              when the old credentials expired. Leave credential fields blank to keep
              the current secret.
            </p>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                Cluster name
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="o-input w-full px-3 py-2 text-sm"
                placeholder="e.g. staging-cluster"
                autoFocus
              />
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                Role
              </label>
              <p className="rounded-md border border-[var(--o-border)] bg-[var(--o-bg-subtle)]/50 px-3 py-2 text-sm text-[var(--o-text-secondary)]">
                {cluster.role} — fixed for this cluster
              </p>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                Authentication
              </label>
              <p className="rounded-md border border-[var(--o-border)] bg-[var(--o-bg-subtle)]/50 px-3 py-2 text-sm text-[var(--o-text-secondary)]">
                {authMethod === "token"
                  ? "Service account token + API URL"
                  : "Kubeconfig"}
              </p>
            </div>

            {authMethod === "token" ? (
              <>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                    API Server URL
                  </label>
                  <input
                    value={apiServerUrl}
                    onChange={(e) => setApiServerUrl(e.target.value)}
                    className="o-input w-full px-3 py-2 text-sm"
                    placeholder="https://api.cluster.example.com:6443"
                  />
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                    Bearer token (optional — paste to rotate)
                  </label>
                  <div className="relative">
                    <textarea
                      value={token}
                      onChange={(e) => setToken(e.target.value)}
                      rows={3}
                      className={clsx(
                        "o-input w-full resize-none px-3 py-2 pr-9 font-mono text-xs",
                        !showToken && token && "[-webkit-text-security:disc]",
                      )}
                      placeholder="Leave blank to keep existing token"
                    />
                    {token && (
                      <button
                        type="button"
                        onClick={() => setShowToken((s) => !s)}
                        className="absolute right-2 top-2 rounded p-0.5 text-[var(--o-text-tertiary)] hover:text-[var(--o-text-secondary)]"
                        tabIndex={-1}
                      >
                        {showToken ? (
                          <EyeOff className="h-3.5 w-3.5" />
                        ) : (
                          <Eye className="h-3.5 w-3.5" />
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                  Kubeconfig YAML (optional — paste to replace)
                </label>
                <div className="relative">
                  <textarea
                    value={kubeconfig}
                    onChange={(e) => setKubeconfig(e.target.value)}
                    rows={6}
                    className={clsx(
                      "o-input w-full resize-none px-3 py-2 pr-9 font-mono text-xs",
                      !showKubeconfig && kubeconfig && "[-webkit-text-security:disc]",
                    )}
                    placeholder="Leave blank to keep existing kubeconfig"
                  />
                  {kubeconfig && (
                    <button
                      type="button"
                      onClick={() => setShowKubeconfig((s) => !s)}
                      className="absolute right-2 top-2 rounded p-0.5 text-[var(--o-text-tertiary)] hover:text-[var(--o-text-secondary)]"
                      tabIndex={-1}
                    >
                      {showKubeconfig ? (
                        <EyeOff className="h-3.5 w-3.5" />
                      ) : (
                        <Eye className="h-3.5 w-3.5" />
                      )}
                    </button>
                  )}
                </div>
              </div>
            )}

            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                Namespace filter (comma-separated, empty = all)
              </label>
              <input
                value={namespacesRaw}
                onChange={(e) => setNamespacesRaw(e.target.value)}
                className="o-input w-full px-3 py-2 text-sm"
                placeholder="default, my-app, monitoring"
              />
            </div>

            <label className="flex items-center gap-2 text-xs text-[var(--o-text-secondary)]">
              <input
                type="checkbox"
                checked={verifySsl}
                onChange={(e) => setVerifySsl(e.target.checked)}
                className="rounded border-[var(--o-border)] bg-[var(--o-bg)]"
              />
              Verify SSL certificate (applies when you save new credentials)
            </label>

            <div className="flex items-center gap-2 rounded-md bg-[var(--o-bg-subtle)]/60 px-3 py-2 text-[11px] text-[var(--o-text-secondary)]">
              <Shield className="h-3.5 w-3.5 shrink-0 text-[var(--o-green)]" />
              New credentials are encrypted before storage
            </div>

            {updateMut.isError && (
              <div className="rounded-md border border-[var(--o-danger)]/30 bg-[var(--o-danger)]/10 px-3 py-2 text-xs text-[var(--o-danger)]">
                {(updateMut.error as Error)?.message ?? "Failed to update cluster"}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                disabled={updateMut.isPending}
                onClick={onClose}
                className="o-btn-ghost px-3 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!name.trim() || updateMut.isPending}
                className="o-btn-success inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
              >
                {updateMut.isPending && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                {updateMut.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
