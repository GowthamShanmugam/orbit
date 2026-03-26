import {
  createSecret,
  deleteSecret,
  getAuditLog,
  listSecrets,
  rotateSecret,
} from "@/api/secrets";
import { useSecretStore } from "@/stores/secretStore";
import type { ProjectSecret, SecretScope } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ClipboardCopy,
  Eye,
  EyeOff,
  Key,
  Plus,
  RefreshCw,
  Shield,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useState } from "react";

interface VaultManagerProps {
  projectId: string;
}

export default function VaultManager({ projectId }: VaultManagerProps) {
  const setSecrets = useSecretStore((s) => s.setSecrets);

  const { data: secrets = [], isLoading } = useQuery({
    queryKey: ["secrets", projectId],
    queryFn: async () => {
      const items = await listSecrets(projectId);
      setSecrets(items);
      return items;
    },
  });

  const [showCreate, setShowCreate] = useState(false);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--o-border)] bg-[var(--o-bg-raised)] px-6 py-4">
        <div className="flex items-center gap-3">
          <Shield className="h-5 w-5 text-[var(--o-orange)]" />
          <div>
            <h1 className="text-lg font-semibold text-[var(--o-text)]">
              Secret Vault
            </h1>
            <p className="text-xs text-[var(--o-text-secondary)]">
              AES-256-GCM encrypted storage — secrets never reach the AI model
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="o-btn-success flex items-center gap-2 px-3 py-1.5 text-xs"
        >
          <Plus className="h-3.5 w-3.5" /> Add Secret
        </button>
      </div>

      {showCreate && (
        <CreateSecretForm
          projectId={projectId}
          onClose={() => setShowCreate(false)}
        />
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-sm text-[var(--o-text-secondary)]">
            Loading secrets…
          </div>
        ) : secrets.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
            <Key className="h-10 w-10 text-[var(--o-border)]" />
            <p className="text-sm text-[var(--o-text-secondary)]">
              No secrets stored yet
            </p>
            <p className="max-w-xs text-xs text-[var(--o-text-quaternary)]">
              Add API keys, tokens, and credentials. They'll be encrypted and
              replaced with safe placeholders in AI prompts.
            </p>
          </div>
        ) : (
          <div className="o-list divide-y divide-[var(--o-border)]">
            {secrets.map((secret) => (
              <SecretRow
                key={secret.id}
                secret={secret}
                projectId={projectId}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SecretRow({
  secret,
  projectId,
}: {
  secret: ProjectSecret;
  projectId: string;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [showRotate, setShowRotate] = useState(false);
  const [copiedPlaceholder, setCopiedPlaceholder] = useState(false);

  const deleteMut = useMutation({
    mutationFn: () => deleteSecret(projectId, secret.id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["secrets", projectId] }),
  });

  const copyPlaceholder = useCallback(() => {
    navigator.clipboard.writeText(secret.placeholder);
    setCopiedPlaceholder(true);
    setTimeout(() => setCopiedPlaceholder(false), 2000);
  }, [secret.placeholder]);

  const scopeColor: Record<string, string> = {
    project: "bg-[var(--o-accent-ring)]/20 text-[var(--o-accent)]",
    team: "bg-[var(--o-purple)]/20 text-[var(--o-purple)]",
    personal: "bg-[var(--o-green)]/20 text-[var(--o-green)]",
  };

  return (
    <div className="o-list-row px-6 py-3">
      <div className="flex items-center gap-3">
        <Key className="h-4 w-4 shrink-0 text-[var(--o-orange)]" />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-[var(--o-text)]">
              {secret.name}
            </span>
            <span
              className={clsx(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                scopeColor[secret.scope] ?? scopeColor.project,
              )}
            >
              {secret.scope}
            </span>
          </div>
          {secret.description && (
            <p className="mt-0.5 text-xs text-[var(--o-text-secondary)]">
              {secret.description}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={copyPlaceholder}
          title="Copy placeholder"
          className="flex items-center gap-1 rounded border border-[var(--o-border)] bg-[var(--o-bg)] px-2 py-1 font-mono text-[10px] text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-accent)] hover:text-[var(--o-accent)]"
        >
          <ClipboardCopy className="h-3 w-3" />
          {copiedPlaceholder ? "Copied!" : secret.placeholder}
        </button>
        <button
          type="button"
          onClick={() => setShowRotate(!showRotate)}
          title="Rotate value"
          className="rounded p-1.5 text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          title="Audit log"
          className="rounded p-1.5 text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
        >
          {expanded ? (
            <EyeOff className="h-3.5 w-3.5" />
          ) : (
            <Eye className="h-3.5 w-3.5" />
          )}
        </button>
        <button
          type="button"
          onClick={() => deleteMut.mutate()}
          disabled={deleteMut.isPending}
          title="Delete secret"
          className="rounded p-1.5 text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-danger)]"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {showRotate && (
        <RotateForm
          projectId={projectId}
          secret={secret}
          onClose={() => setShowRotate(false)}
        />
      )}

      {expanded && (
        <AuditSection projectId={projectId} secretId={secret.id} />
      )}

      <div className="mt-1.5 flex gap-4 text-[10px] text-[var(--o-text-quaternary)]">
        <span>Created {new Date(secret.created_at).toLocaleDateString()}</span>
        {secret.last_rotated && (
          <span>
            Rotated {new Date(secret.last_rotated).toLocaleDateString()}
          </span>
        )}
        <span>{secret.vault_backend}</span>
      </div>
    </div>
  );
}

function CreateSecretForm({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [scope, setScope] = useState<SecretScope>("project");
  const [description, setDescription] = useState("");

  const createMut = useMutation({
    mutationFn: () =>
      createSecret(projectId, { name, value, scope, description: description || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["secrets", projectId] });
      onClose();
    },
  });

  return (
    <div className="border-b border-[var(--o-border)] bg-[var(--o-bg)] p-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-[var(--o-text)]">Add Secret</h3>
        <button type="button" onClick={onClose} className="text-[var(--o-text-secondary)] hover:text-[var(--o-text)]">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Secret name (e.g. github_token)"
          className="o-input px-3 py-2 text-xs"
        />
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value as SecretScope)}
          className="o-input px-3 py-2 text-xs"
        >
          <option value="project">Project</option>
          <option value="team">Team</option>
          <option value="personal">Personal</option>
        </select>
      </div>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        type="password"
        placeholder="Secret value"
        className="o-input mt-3 w-full px-3 py-2 text-xs"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description (optional)"
        className="o-input mt-3 w-full px-3 py-2 text-xs"
      />
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="o-btn-ghost px-3 py-1.5 text-xs"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => createMut.mutate()}
          disabled={!name.trim() || !value.trim() || createMut.isPending}
          className={clsx(
            "o-btn-success px-3 py-1.5 text-xs",
            (!name.trim() || !value.trim() || createMut.isPending) && "cursor-not-allowed opacity-50",
          )}
        >
          {createMut.isPending ? "Encrypting…" : "Encrypt & Save"}
        </button>
      </div>
      {createMut.isError && (
        <p className="mt-2 text-xs text-[var(--o-danger)]">
          {(createMut.error as Error)?.message ?? "Failed to create secret"}
        </p>
      )}
    </div>
  );
}

function RotateForm({
  projectId,
  secret,
  onClose,
}: {
  projectId: string;
  secret: ProjectSecret;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");

  const rotateMut = useMutation({
    mutationFn: () => rotateSecret(projectId, secret.id, { value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["secrets", projectId] });
      onClose();
    },
  });

  return (
    <div className="mt-2 flex gap-2">
      <input
        type="password"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="New secret value"
        className="o-input flex-1 px-2 py-1.5 text-xs"
      />
      <button
        type="button"
        onClick={() => rotateMut.mutate()}
        disabled={!value.trim() || rotateMut.isPending}
        className="o-btn-primary px-3 py-1.5 text-xs disabled:opacity-50"
      >
        Rotate
      </button>
      <button
        type="button"
        onClick={onClose}
        className="o-btn-ghost px-2 py-1.5 text-xs"
      >
        Cancel
      </button>
    </div>
  );
}

function AuditSection({
  projectId,
  secretId,
}: {
  projectId: string;
  secretId: string;
}) {
  const { data: logs = [], isLoading } = useQuery({
    queryKey: ["secret-audit", projectId, secretId],
    queryFn: () => getAuditLog(projectId, secretId),
  });

  if (isLoading) {
    return (
      <p className="mt-2 text-[10px] text-[var(--o-text-secondary)]">Loading audit log…</p>
    );
  }
  if (logs.length === 0) {
    return <p className="mt-2 text-[10px] text-[var(--o-text-quaternary)]">No audit entries</p>;
  }

  return (
    <div className="mt-2 max-h-32 overflow-y-auto rounded border border-[var(--o-bg-subtle)] bg-[var(--o-bg)]">
      {logs.map((entry) => (
        <div
          key={entry.id}
          className="flex items-center gap-3 border-b border-[var(--o-bg-subtle)] px-3 py-1.5 last:border-b-0"
        >
          <span className="text-[10px] font-mono text-[var(--o-text-quaternary)]">
            {new Date(entry.created_at).toLocaleString()}
          </span>
          <span
            className={clsx(
              "rounded px-1.5 py-0.5 text-[10px] font-medium",
              entry.action === "created" && "bg-[var(--o-green-bg)]/20 text-[var(--o-green)]",
              entry.action === "accessed" && "bg-[var(--o-accent-ring)]/20 text-[var(--o-accent)]",
              entry.action === "rotated" && "bg-[var(--o-warning)]/20 text-[var(--o-warning)]",
              entry.action === "deleted" && "bg-[var(--o-danger)]/20 text-[var(--o-danger)]",
            )}
          >
            {entry.action}
          </span>
          {entry.details && (
            <span className="text-[10px] text-[var(--o-text-secondary)] truncate">
              {entry.details}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
