import { createSecret, deleteSecret, getAuditLog, listSecrets, rotateSecret } from "@/api/secrets";
import { useSecretStore } from "@/stores/secretStore";
import type { ProjectSecret } from "@/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ClipboardCopy, Eye, EyeOff, Key, KeyRound, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useCallback, useState } from "react";

interface VaultManagerProps {
  readOnly?: boolean;
}

export default function VaultManager({ readOnly = false }: VaultManagerProps) {
  const setSecrets = useSecretStore((s) => s.setSecrets);

  const { data: secrets = [], isLoading } = useQuery({
    queryKey: ["secrets"],
    queryFn: async () => {
      const items = await listSecrets();
      setSecrets(items);
      return items;
    },
  });

  const [showCreate, setShowCreate] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--o-accent-muted)]">
            <KeyRound className="h-5 w-5 text-[var(--o-accent)]" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-[var(--o-text)]">Secrets</h1>
            <p className="text-sm text-[var(--o-text-secondary)]">
              Personal API keys and credentials. Encrypted with AES-256-GCM — never sent to the AI model.
            </p>
          </div>
        </div>
        {!readOnly && (
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            Add Secret
          </button>
        )}
      </div>

      {showCreate && !readOnly && (
        <CreateSecretForm onClose={() => setShowCreate(false)} />
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-16 text-sm text-[var(--o-text-secondary)]">
          Loading secrets…
        </div>
      ) : secrets.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <Key className="h-10 w-10 text-[var(--o-text-quaternary)]" />
          <p className="text-sm text-[var(--o-text-secondary)]">No secrets stored yet</p>
          <p className="max-w-xs text-xs text-[var(--o-text-quaternary)]">
            Add API keys, tokens, and credentials. They&apos;ll be encrypted and replaced with safe
            placeholders in AI prompts.
          </p>
        </div>
      ) : (
        <div className="o-list box-border max-w-full divide-y divide-[var(--o-border)]">
          {secrets.map((secret) => (
            <SecretRow
              key={secret.id}
              secret={secret}
              readOnly={readOnly}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SecretRow({
  secret,
  readOnly,
}: {
  secret: ProjectSecret;
  readOnly: boolean;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [showRotate, setShowRotate] = useState(false);
  const [copiedPlaceholder, setCopiedPlaceholder] = useState(false);

  const deleteMut = useMutation({
    mutationFn: () => deleteSecret(secret.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["secrets"] }),
  });

  const copyPlaceholder = useCallback(() => {
    navigator.clipboard.writeText(secret.placeholder);
    setCopiedPlaceholder(true);
    setTimeout(() => setCopiedPlaceholder(false), 2000);
  }, [secret.placeholder]);

  return (
    <div className="o-list-row px-4 py-3 sm:px-6">
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <Key className="mt-0.5 h-4 w-4 shrink-0 text-orange-500" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-[var(--o-text)]">{secret.name}</span>
            </div>
            {secret.description && (
              <p className="mt-0.5 text-xs text-[var(--o-text-secondary)]">{secret.description}</p>
            )}
          </div>
        </div>
        <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-2 sm:justify-end">
          <button
            type="button"
            onClick={copyPlaceholder}
            title="Copy placeholder"
            className="flex max-w-full min-w-0 items-center gap-1 rounded border border-[var(--o-border)] bg-[var(--o-bg)] px-2 py-1 font-mono text-[10px] text-[var(--o-text-secondary)] transition-colors hover:border-[var(--o-accent)] hover:text-[var(--o-accent)]"
          >
            <ClipboardCopy className="h-3 w-3 shrink-0" />
            <span className="truncate">{copiedPlaceholder ? "Copied!" : secret.placeholder}</span>
          </button>
          {!readOnly && (
            <button
              type="button"
              onClick={() => setShowRotate(!showRotate)}
              title="Rotate value"
              className="rounded p-1.5 text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            title="Audit log"
            className="rounded p-1.5 text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-text)]"
          >
            {expanded ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </button>
          {!readOnly && (
            <button
              type="button"
              onClick={() => deleteMut.mutate()}
              disabled={deleteMut.isPending}
              title="Delete secret"
              className="rounded p-1.5 text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)] hover:text-[var(--o-danger)]"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {showRotate && (
        <RotateForm secret={secret} onClose={() => setShowRotate(false)} />
      )}

      {expanded && <AuditSection secretId={secret.id} />}

      <div className="mt-1.5 flex gap-4 text-[10px] text-[var(--o-text-quaternary)]">
        <span>Created {new Date(secret.created_at).toLocaleDateString()}</span>
        {secret.last_rotated && (
          <span>Rotated {new Date(secret.last_rotated).toLocaleDateString()}</span>
        )}
        <span>{secret.vault_backend}</span>
      </div>
    </div>
  );
}

function CreateSecretForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");

  const createMut = useMutation({
    mutationFn: () =>
      createSecret({ name, value, description: description || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["secrets"] });
      onClose();
    },
  });

  return (
    <div className="border-b border-[var(--o-border)] bg-[var(--o-bg)] p-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-[var(--o-text)]">Add Secret</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-[var(--o-text-secondary)] hover:text-[var(--o-text)]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Secret name (e.g. github_token)"
        className="o-input w-full px-3 py-2 text-xs"
      />
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
        <button type="button" onClick={onClose} className="o-btn-ghost px-3 py-1.5 text-xs">
          Cancel
        </button>
        <button
          type="button"
          onClick={() => createMut.mutate()}
          disabled={!name.trim() || !value.trim() || createMut.isPending}
          className={clsx(
            "o-btn-success px-3 py-1.5 text-xs",
            (!name.trim() || !value.trim() || createMut.isPending) &&
              "cursor-not-allowed opacity-50",
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
  secret,
  onClose,
}: {
  secret: ProjectSecret;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");

  const rotateMut = useMutation({
    mutationFn: () => rotateSecret(secret.id, { value }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["secrets"] });
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
      <button type="button" onClick={onClose} className="o-btn-ghost px-2 py-1.5 text-xs">
        Cancel
      </button>
    </div>
  );
}

function AuditSection({ secretId }: { secretId: string }) {
  const { data: logs = [], isLoading } = useQuery({
    queryKey: ["secret-audit", secretId],
    queryFn: () => getAuditLog(secretId),
  });

  if (isLoading) {
    return <p className="mt-2 text-[10px] text-[var(--o-text-secondary)]">Loading audit log…</p>;
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
              entry.action === "created" && "bg-[var(--o-pastel-sage)] text-[var(--o-pastel-sage-fg)]",
              entry.action === "accessed" && "bg-[var(--o-pastel-mint)] text-[var(--o-pastel-mint-fg)]",
              entry.action === "rotated" && "bg-[var(--o-pastel-peach)] text-[var(--o-pastel-peach-fg)]",
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
