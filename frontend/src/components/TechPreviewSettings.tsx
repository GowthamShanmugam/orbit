import { getFeatureFlags, putFeatureFlags } from "@/api/aiRules";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";

const TECH_PREVIEW_FEATURES: { key: string; label: string; description: string }[] = [
  {
    key: "system_map",
    label: "System Map",
    description:
      "Auto-discover deployments from context clusters and map them to repositories. " +
      "The AI uses this map to understand your architecture.",
  },
];

const QK = ["global-feature-flags"] as const;

export default function TechPreviewSettings() {
  const queryClient = useQueryClient();

  const { data: flags = {}, isLoading } = useQuery({
    queryKey: QK,
    queryFn: getFeatureFlags,
  });

  const toggleMut = useMutation({
    mutationFn: (patch: Record<string, boolean>) => putFeatureFlags(patch),
    onSuccess: (updated) => {
      queryClient.setQueryData(QK, updated);
    },
  });

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-[var(--o-accent)]" />
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--o-text-tertiary)]">
            Tech Preview
          </h3>
        </div>
        <p className="mt-1 text-xs text-[var(--o-text-tertiary)]">
          Enable experimental features across all projects. These may change or be removed.
        </p>
      </div>

      {isLoading ? (
        <p className="text-xs text-[var(--o-text-tertiary)]">Loading...</p>
      ) : (
        <div className="space-y-2">
          {TECH_PREVIEW_FEATURES.map((feat) => {
            const enabled = flags[feat.key] === true;
            return (
              <label
                key={feat.key}
                className="flex items-start gap-3 rounded-lg border border-[var(--o-border)] bg-[var(--o-surface)]/40 p-3 cursor-pointer"
              >
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 accent-[var(--o-accent)]"
                  checked={enabled}
                  disabled={toggleMut.isPending}
                  onChange={() => toggleMut.mutate({ [feat.key]: !enabled })}
                />
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-medium text-[var(--o-text)]">{feat.label}</span>
                  <p className="mt-0.5 text-xs text-[var(--o-text-tertiary)]">{feat.description}</p>
                </div>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
