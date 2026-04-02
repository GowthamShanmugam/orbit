import { createCluster } from "@/api/clusters";
import type { ClusterAuthMethod, ClusterRole, ProjectCluster } from "@/types";
import clsx from "clsx";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Eye, EyeOff, Loader2, Shield, X, XCircle } from "lucide-react";
import { useState } from "react";

interface Props {
  projectId: string;
  onClose: () => void;
}

export default function AddClusterModal({ projectId, onClose }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [role, setRole] = useState<ClusterRole>("context");
  const [authMethod, setAuthMethod] = useState<ClusterAuthMethod>("token");
  const [apiServerUrl, setApiServerUrl] = useState("");
  const [token, setToken] = useState("");
  const [kubeconfig, setKubeconfig] = useState("");
  const [namespacesRaw, setNamespacesRaw] = useState("");
  const [verifySsl, setVerifySsl] = useState(true);
  const [showToken, setShowToken] = useState(false);
  const [showKubeconfig, setShowKubeconfig] = useState(false);
  const [result, setResult] = useState<ProjectCluster | null>(null);

  const createMut = useMutation({
    mutationFn: () => {
      const credentials: Record<string, unknown> =
        authMethod === "token"
          ? { token, api_server_url: apiServerUrl, verify_ssl: verifySsl }
          : { kubeconfig, verify_ssl: verifySsl };

      const namespaceFilter = namespacesRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

      return createCluster(projectId, {
        name: name.trim(),
        role,
        auth_method: authMethod,
        credentials,
        api_server_url: authMethod === "token" ? apiServerUrl : undefined,
        namespace_filter: namespaceFilter.length ? namespaceFilter : undefined,
      });
    },
    onSuccess: (cluster) => {
      qc.invalidateQueries({ queryKey: ["clusters", projectId] });
      setResult(cluster);
    },
  });

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center o-modal-backdrop p-4"
      onClick={() => !createMut.isPending && onClose()}
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
            Add Cluster
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
                    ? `Cluster "${result.name}" connected`
                    : `Cluster "${result.name}" saved but unreachable`}
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
            if (!name.trim() || createMut.isPending) return;
            createMut.mutate();
          }}
        >
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
            <div className="flex gap-3">
              {(["context", "test"] as const).map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRole(r)}
                  className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                    role === r
                      ? r === "context"
                        ? "border-[var(--o-accent)] bg-[var(--o-accent)]/10 text-[var(--o-accent)]"
                        : "border-[var(--o-warning)] bg-[var(--o-warning)]/10 text-[var(--o-warning)]"
                      : "border-[var(--o-border)] bg-[var(--o-bg)] text-[var(--o-text-secondary)] hover:border-[var(--o-border-subtle)]"
                  }`}
                >
                  {r === "context" ? "Context (read-only)" : "Test (read-write)"}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-[var(--o-text-secondary)]">
              {role === "context"
                ? "Read-only cluster for AI context — pods, CRDs, events, logs"
                : "Read-write cluster for running e2e tests and applying manifests"}
            </p>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
              Authentication method
            </label>
            <select
              value={authMethod}
              onChange={(e) =>
                setAuthMethod(e.target.value as ClusterAuthMethod)
              }
              className="o-input w-full px-3 py-2 text-sm"
            >
              <option value="token">Service Account Token + API URL</option>
              <option value="kubeconfig">Kubeconfig</option>
            </select>
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
                  Bearer Token
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
                    placeholder="eyJhbGciOi..."
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
                Kubeconfig (YAML)
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
                  placeholder="apiVersion: v1\nkind: Config\n..."
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
              Namespace filter (comma-separated, leave empty for all)
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
            Verify SSL certificate
          </label>

          <div className="flex items-center gap-2 rounded-md bg-[var(--o-bg-subtle)]/60 px-3 py-2 text-[11px] text-[var(--o-text-secondary)]">
            <Shield className="h-3.5 w-3.5 shrink-0 text-[var(--o-green)]" />
            Credentials are encrypted with AES-256-GCM before storage — never stored in plain text
          </div>

          {createMut.isError && (
            <div className="rounded-md border border-[var(--o-danger)]/30 bg-[var(--o-danger)]/10 px-3 py-2 text-xs text-[var(--o-danger)]">
              {(createMut.error as Error)?.message ?? "Failed to create cluster"}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              disabled={createMut.isPending}
              onClick={onClose}
              className="o-btn-ghost px-3 py-2 text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || createMut.isPending}
              className="o-btn-success inline-flex items-center gap-2 px-4 py-2 text-sm disabled:opacity-50"
            >
              {createMut.isPending && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              {createMut.isPending ? "Connecting…" : "Add & Test Connection"}
            </button>
          </div>
        </form>
        )}
      </div>
    </div>
  );
}
