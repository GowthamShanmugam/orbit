import { useState, useCallback } from "react";
import { useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Loader2, Map, Settings2 } from "lucide-react";
import { getMappings, getMapStatus, getHierarchy } from "@/api/systemMap";
import SetupWizard from "./SetupWizard";
import MapCanvas from "./MapCanvas";
import DetailPanel from "./DetailPanel";
import type { ServiceMappingResponse } from "@/types";

interface Props {
  projectId: string;
  readOnly?: boolean;
}

export default function SystemMap({ projectId, readOnly = false }: Props) {
  const queryClient = useQueryClient();
  const [selectedMappingId, setSelectedMappingId] = useState<string | null>(null);
  const [showReconfigure, setShowReconfigure] = useState(false);

  const mappingsQuery = useQuery({
    queryKey: ["system-map-mappings", projectId],
    queryFn: () => getMappings(projectId),
  });

  const statusQuery = useQuery({
    queryKey: ["system-map-status", projectId],
    queryFn: () => getMapStatus(projectId),
    enabled: (mappingsQuery.data?.length ?? 0) > 0,
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  });

  const hierarchyQuery = useQuery({
    queryKey: ["system-map-hierarchy", projectId],
    queryFn: () => getHierarchy(projectId),
    enabled: (mappingsQuery.data?.length ?? 0) > 0,
    placeholderData: keepPreviousData,
  });

  const hasMappings = (mappingsQuery.data?.length ?? 0) > 0;
  const selectedMapping = mappingsQuery.data?.find(
    (m: ServiceMappingResponse) => m.id === selectedMappingId,
  );
  const selectedStatus = statusQuery.data?.find((s) => s.mapping_id === selectedMappingId);

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["system-map-status", projectId] });
    queryClient.invalidateQueries({ queryKey: ["system-map-mappings", projectId] });
    queryClient.invalidateQueries({ queryKey: ["system-map-hierarchy", projectId] });
  }, [queryClient, projectId]);

  const handleSetupComplete = useCallback(() => {
    setShowReconfigure(false);
    handleRefresh();
  }, [handleRefresh]);

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
          <button
            type="button"
            className="o-btn-ghost flex items-center gap-1 text-xs"
            onClick={() => setShowReconfigure(true)}
          >
            <Settings2 className="h-3 w-3" />
            Reconfigure
          </button>
        )}
      </div>

      <div className="relative">
        <MapCanvas
          projectId={projectId}
          mappings={mappingsQuery.data ?? []}
          edges={[]}
          statusItems={statusQuery.data ?? []}
          hierarchyEdges={hierarchyQuery.data ?? []}
          onNodeClick={setSelectedMappingId}
          onRefresh={handleRefresh}
          readOnly={readOnly}
        />

        {selectedMapping && (
          <DetailPanel
            projectId={projectId}
            mapping={selectedMapping}
            statusItem={selectedStatus}
            onClose={() => setSelectedMappingId(null)}
          />
        )}
      </div>

      <p className="mt-3 text-[10px] text-[var(--o-text-secondary)]">
        Operator deployments (top) connect to the services they manage. Click any service to see
        live pods, logs, events, and version info. Use "Ask Orbi" to debug with full context.
      </p>
    </div>
  );
}
