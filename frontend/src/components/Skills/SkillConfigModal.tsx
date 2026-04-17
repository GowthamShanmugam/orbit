import { configureIntegration, startGoogleDriveOAuth } from "@/api/skills";
import type { Integration } from "@/types";
type McpSkill = Integration;
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  Loader2,
  X,
  XCircle,
  CloudUpload,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

interface Props {
  skill: McpSkill;
  onClose: () => void;
  onSaved: () => void;
}

function isOAuthIntegration(skill: McpSkill): boolean {
  return skill.config_schema?.config_type === "oauth";
}

export default function SkillConfigModal({ skill, onClose, onSaved }: Props) {
  if (isOAuthIntegration(skill)) {
    return <OAuthConfigModal skill={skill} onClose={onClose} onSaved={onSaved} />;
  }
  return <TokenConfigModal skill={skill} onClose={onClose} onSaved={onSaved} />;
}

// ---------------------------------------------------------------------------
// Token-based config (JIRA, GitHub, etc.) -- original modal
// ---------------------------------------------------------------------------

function TokenConfigModal({ skill, onClose, onSaved }: Props) {
  const fields = skill.config_schema?.fields ?? [];
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const f of fields) {
      initial[f.key] = "";
    }
    return initial;
  });
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});

  const saveMut = useMutation({
    mutationFn: () => configureIntegration(skill.id, { config_values: values }),
    onSuccess: (updated) => {
      if (updated.status === "connected") {
        setTimeout(() => onSaved(), 1200);
      }
    },
  });

  const allRequiredFilled = fields.filter((f) => f.required).every((f) => values[f.key]?.trim());

  const result = saveMut.data;
  const connected = result?.status === "connected";
  const failed = result?.status === "error";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--o-border)] px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--o-text)]">Configure {skill.name}</h2>
            <p className="mt-0.5 text-xs text-[var(--o-text-secondary)]">
              Provide credentials to connect this MCP skill
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="o-btn-icon rounded-lg p-1.5 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-6 py-5">
          {fields.map((field) => (
            <div key={field.key}>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                {field.label}
                {field.required && <span className="ml-0.5 text-[var(--o-danger)]">*</span>}
              </label>
              <div className="relative">
                <input
                  type={
                    field.type === "password" && !showPasswords[field.key] ? "password" : "text"
                  }
                  value={values[field.key] ?? ""}
                  onChange={(e) => setValues((prev) => ({ ...prev, [field.key]: e.target.value }))}
                  placeholder={field.placeholder ?? ""}
                  disabled={saveMut.isPending || connected}
                  className="o-input w-full rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-sm text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--o-accent)] disabled:opacity-50"
                />
                {field.type === "password" && (
                  <button
                    type="button"
                    onClick={() =>
                      setShowPasswords((p) => ({
                        ...p,
                        [field.key]: !p[field.key],
                      }))
                    }
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--o-text-tertiary)] hover:text-[var(--o-text)]"
                  >
                    {showPasswords[field.key] ? (
                      <EyeOff className="h-3.5 w-3.5" />
                    ) : (
                      <Eye className="h-3.5 w-3.5" />
                    )}
                  </button>
                )}
              </div>
              {field.help_url && (
                <a
                  href={field.help_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-[var(--o-accent)] transition-opacity hover:opacity-80"
                >
                  <ExternalLink className="h-3 w-3" />
                  {field.help_text ?? "Learn more"}
                </a>
              )}
            </div>
          ))}

          {fields.length === 0 && (
            <p className="text-sm text-[var(--o-text-secondary)]">
              This skill has no configuration fields.
            </p>
          )}

          <StatusBanner status={result?.status} message={result?.status_message} toolCount={result?.tool_count} />

          {saveMut.isError && (
            <p
              className="rounded px-3 py-2 text-xs text-[var(--o-danger)]"
              style={{
                backgroundColor: "color-mix(in srgb, var(--o-danger) 10%, transparent)",
              }}
            >
              Failed to save: {(saveMut.error as Error)?.message ?? "Unknown error"}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-[var(--o-border)] px-6 py-4">
          <button
            type="button"
            onClick={connected ? onSaved : onClose}
            className="rounded-lg border border-[var(--o-border)] px-4 py-2 text-xs font-medium text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)]"
          >
            {connected ? "Done" : "Cancel"}
          </button>
          {!connected && (
            <button
              type="button"
              onClick={() => saveMut.mutate()}
              disabled={!allRequiredFilled || saveMut.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-4 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saveMut.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
              {saveMut.isPending ? "Connecting..." : failed ? "Retry" : "Save & Connect"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OAuth-based config (Google Drive)
// ---------------------------------------------------------------------------

function OAuthConfigModal({ skill, onClose, onSaved }: Props) {
  const qc = useQueryClient();
  const [clientJson, setClientJson] = useState("");
  const [step, setStep] = useState<"paste" | "authorizing" | "connected" | "error">(
    skill.status === "connected" ? "connected" : "paste",
  );
  const [callbackUrl, setCallbackUrl] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const handleOAuthMessage = useCallback(
    (event: MessageEvent) => {
      if (event.data?.type === "oauth-complete" && event.data?.provider === "google-drive") {
        setStep("connected");
        qc.invalidateQueries({ queryKey: ["integrations"] });
        setTimeout(() => onSaved(), 1500);
      } else if (event.data?.type === "oauth-error" && event.data?.provider === "google-drive") {
        setStep("error");
        setErrorMsg(event.data?.error || "Authorization failed");
      }
    },
    [onSaved, qc],
  );

  useEffect(() => {
    window.addEventListener("message", handleOAuthMessage);
    return () => window.removeEventListener("message", handleOAuthMessage);
  }, [handleOAuthMessage]);

  const startMut = useMutation({
    mutationFn: () => startGoogleDriveOAuth(clientJson),
    onSuccess: (data) => {
      setCallbackUrl(data.callback_url);
      setStep("authorizing");
      const w = 500;
      const h = 600;
      const left = window.screenX + (window.innerWidth - w) / 2;
      const top = window.screenY + (window.innerHeight - h) / 2;
      const popup = window.open(
        data.auth_url,
        "google-oauth",
        `width=${w},height=${h},left=${left},top=${top},popup=yes`,
      );
      if (!popup) {
        setStep("error");
        setErrorMsg("Popup blocked. Please allow popups for this site.");
      }
    },
    onError: (err) => {
      setStep("error");
      setErrorMsg((err as Error)?.message ?? "Failed to start OAuth flow");
    },
  });

  const isAlreadyConnected = skill.status === "connected";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-[var(--o-border)] bg-[var(--o-bg-raised)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--o-border)] px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--o-text)]">
              {isAlreadyConnected ? "Reconnect" : "Connect"} {skill.name}
            </h2>
            <p className="mt-0.5 text-xs text-[var(--o-text-secondary)]">
              OAuth 2.0 authorization via Google
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="o-btn-icon rounded-lg p-1.5 text-[var(--o-text-tertiary)] hover:bg-[var(--o-bg-subtle)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-6 py-5">
          {/* Step 1: Setup instructions */}
          <div className="space-y-3">
            <div className="rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] p-4">
              <h3 className="text-xs font-semibold text-[var(--o-text)] mb-2">Setup Instructions</h3>
              <ol className="space-y-1.5 text-[11px] text-[var(--o-text-secondary)] list-decimal pl-4">
                <li>
                  Go to{" "}
                  <a
                    href="https://console.cloud.google.com/apis/credentials"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--o-accent)] hover:underline"
                  >
                    Google Cloud Console &rarr; Credentials
                  </a>
                </li>
                <li>Create an OAuth 2.0 Client ID (type: <strong>Web application</strong>)</li>
                <li>
                  Add this as an authorized redirect URI:
                  {callbackUrl ? (
                    <code className="block mt-1 break-all rounded bg-[var(--o-bg-subtle)] px-2 py-1 text-[10px] font-mono text-[var(--o-text)]">
                      {callbackUrl}
                    </code>
                  ) : (
                    <code className="block mt-1 break-all rounded bg-[var(--o-bg-subtle)] px-2 py-1 text-[10px] font-mono text-[var(--o-text-tertiary)]">
                      {window.location.origin.replace(":5173", ":8000")}/oauth/google-drive/callback
                    </code>
                  )}
                </li>
                <li>Enable the <strong>Google Drive API</strong> in your project</li>
                <li>Download the OAuth Client JSON and paste it below</li>
              </ol>
            </div>

            {/* Client JSON textarea */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-[var(--o-text-secondary)]">
                OAuth Client JSON <span className="text-[var(--o-danger)]">*</span>
              </label>
              <textarea
                value={clientJson}
                onChange={(e) => setClientJson(e.target.value)}
                placeholder='{"web":{"client_id":"...","client_secret":"..."}}'
                disabled={step === "authorizing" || step === "connected"}
                rows={5}
                className="o-input w-full rounded-lg border border-[var(--o-border)] bg-[var(--o-bg)] px-3 py-2 text-xs font-mono text-[var(--o-text)] placeholder:text-[var(--o-text-tertiary)] focus:border-[var(--o-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--o-accent)] disabled:opacity-50 resize-none"
              />
              <p className="mt-1 text-[10px] text-[var(--o-text-tertiary)]">
                This JSON is encrypted before storage. Orbit never stores it in plain text.
              </p>
            </div>
          </div>

          {/* Status banners */}
          {step === "authorizing" && (
            <div
              className="flex items-center gap-2 rounded-lg border px-4 py-3 text-xs text-[var(--o-accent)]"
              style={{
                borderColor: "color-mix(in srgb, var(--o-accent) 22%, transparent)",
                backgroundColor: "color-mix(in srgb, var(--o-accent) 6%, transparent)",
              }}
            >
              <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
              <div>
                <p className="font-semibold">Waiting for Google authorization...</p>
                <p className="mt-0.5 opacity-80">Complete the sign-in in the popup window</p>
              </div>
            </div>
          )}

          {step === "connected" && (
            <div
              className="flex items-center gap-2 rounded-lg border px-4 py-3 text-xs text-[var(--o-green)]"
              style={{
                borderColor: "color-mix(in srgb, var(--o-green) 22%, transparent)",
                backgroundColor: "color-mix(in srgb, var(--o-green) 6%, transparent)",
              }}
            >
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <div>
                <p className="font-semibold">Google Drive connected successfully</p>
                <p className="mt-0.5 opacity-80">Your credentials are encrypted and stored securely</p>
              </div>
            </div>
          )}

          {step === "error" && (
            <div
              className="flex items-start gap-2 rounded-lg border px-4 py-3 text-xs text-[var(--o-danger)]"
              style={{
                borderColor: "color-mix(in srgb, var(--o-danger) 22%, transparent)",
                backgroundColor: "color-mix(in srgb, var(--o-danger) 6%, transparent)",
              }}
            >
              <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="min-w-0">
                <p className="font-semibold">Authorization failed</p>
                {errorMsg && (
                  <p className="mt-0.5 break-words opacity-80" style={{ overflowWrap: "anywhere" }}>
                    {errorMsg}
                  </p>
                )}
              </div>
            </div>
          )}

          {startMut.isError && step !== "error" && (
            <p
              className="rounded px-3 py-2 text-xs text-[var(--o-danger)]"
              style={{
                backgroundColor: "color-mix(in srgb, var(--o-danger) 10%, transparent)",
              }}
            >
              {(startMut.error as Error)?.message ?? "Unknown error"}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-[var(--o-border)] px-6 py-4">
          <button
            type="button"
            onClick={step === "connected" ? onSaved : onClose}
            className="rounded-lg border border-[var(--o-border)] px-4 py-2 text-xs font-medium text-[var(--o-text-secondary)] transition-colors hover:bg-[var(--o-bg-subtle)]"
          >
            {step === "connected" ? "Done" : "Cancel"}
          </button>
          {step !== "connected" && (
            <button
              type="button"
              onClick={() => {
                setStep("paste");
                setErrorMsg("");
                startMut.mutate();
              }}
              disabled={!clientJson.trim() || startMut.isPending || step === "authorizing"}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--o-accent)] px-4 py-2 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {startMut.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <CloudUpload className="h-3 w-3" />
              )}
              {startMut.isPending
                ? "Starting..."
                : step === "error"
                  ? "Retry"
                  : isAlreadyConnected
                    ? "Reconnect"
                    : "Connect to Google"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared status banner
// ---------------------------------------------------------------------------

function StatusBanner({
  status,
  message,
  toolCount,
}: {
  status?: string;
  message?: string | null;
  toolCount?: number;
}) {
  if (status === "connected") {
    return (
      <div
        className="flex items-center gap-2 rounded-lg border px-4 py-3 text-xs text-[var(--o-green)]"
        style={{
          borderColor: "color-mix(in srgb, var(--o-green) 22%, transparent)",
          backgroundColor: "color-mix(in srgb, var(--o-green) 6%, transparent)",
        }}
      >
        <CheckCircle2 className="h-4 w-4 shrink-0" />
        <div>
          <p className="font-semibold">Connected successfully</p>
          {toolCount != null && toolCount > 0 && (
            <p className="mt-0.5 opacity-80">{toolCount} tools available</p>
          )}
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div
        className="flex items-start gap-2 rounded-lg border px-4 py-3 text-xs text-[var(--o-danger)]"
        style={{
          borderColor: "color-mix(in srgb, var(--o-danger) 22%, transparent)",
          backgroundColor: "color-mix(in srgb, var(--o-danger) 6%, transparent)",
        }}
      >
        <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0">
          <p className="font-semibold">Connection failed</p>
          {message && (
            <p className="mt-0.5 break-words opacity-80" style={{ overflowWrap: "anywhere" }}>
              {message}
            </p>
          )}
        </div>
      </div>
    );
  }

  return null;
}
