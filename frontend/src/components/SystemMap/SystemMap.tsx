import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Map, Settings2, Trash2 } from "lucide-react";
import { getMappings, deleteSystemMap } from "@/api/systemMap";
import SetupWizard from "./SetupWizard";
import MapCanvas from "./MapCanvas";

interface Props {
  projectId: string;
  readOnly?: boolean;
}

export default function SystemMap({ projectId, readOnly = false }: Props) {
  const queryClient = useQueryClient();
  const [showReconfigure, setShowReconfigure] = useState(false);

  const mappingsQuery = useQuery({
    queryKey: ["system-map-mappings", projectId],
    queryFn: () => getMappings(projectId),
  });

  const hasMappings = (mappingsQuery.data?.length ?? 0) > 0;

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["system-map-mappings", projectId] });
  }, [queryClient, projectId]);

  const handleSetupComplete = useCallback(() => {
    setShowReconfigure(false);
    handleRefresh();
  }, [handleRefresh]);

  const deleteMut = useMutation({
    mutationFn: () => deleteSystemMap(projectId),
    onSuccess: () => {
      queryClient.setQueryData(["system-map-mappings", projectId], []);
    },
  });

  if (mappingsQuery.isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-[var(--o-text-secondary)]">
        <Loader2 className="mb-3 h-6 w-6 animate-spin" />
        <p className="text-sm">Loading system map...</p>
      </div>
    );
  }

  if (!hasMappings || showReconfigure) {
    return (
      <div>
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Map className="h-5 w-5 text-[var(--o-accent)]" />
            <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--o-text-secondary)]">
              System Map
            </h2>
          </div>
          {showReconfigure && (
            <button
              type="button"
              className="o-btn-ghost text-xs"
              onClick={() => setShowReconfigure(false)}
            >
              Cancel
            </button>
          )}
        </div>
        <SetupWizard projectId={projectId} onComplete={handleSetupComplete} />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Map className="h-5 w-5 text-[var(--o-accent)]" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--o-text-secondary)]">
            System Map
          </h2>
          <span className="o-badge text-[10px]">{mappingsQuery.data?.length ?? 0} services</span>
        </div>
        {!readOnly && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="o-btn-ghost flex items-center gap-1 text-xs"
              onClick={() => setShowReconfigure(true)}
            >
              <Settings2 className="h-3 w-3" />
              Reconfigure
            </button>
            <button
              type="button"
              className="o-btn-ghost flex items-center gap-1 text-xs text-red-400 hover:text-red-300"
              onClick={() => {
                if (window.confirm("Delete the entire system map? This removes all mappings.")) {
                  deleteMut.mutate();
                }
              }}
              disabled={deleteMut.isPending}
            >
              <Trash2 className="h-3 w-3" />
              {deleteMut.isPending ? "Deleting..." : "Delete Map"}
            </button>
          </div>
        )}
      </div>

      <MapCanvas
        mappings={mappingsQuery.data ?? []}
        onNodeClick={() => {}}
      />

      <p className="mt-3 text-[10px] text-[var(--o-text-secondary)]">
        Deployments grouped by context source. The AI uses this map to understand
        your architecture when answering questions. Click Reconfigure to update mappings.
      </p>
    </div>
  );
}
