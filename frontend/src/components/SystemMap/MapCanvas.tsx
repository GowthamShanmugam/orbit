import { useCallback, useEffect, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  BackgroundVariant,
  Panel,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { RefreshCw } from "lucide-react";
import ServiceNode from "./ServiceNode";
import type {
  ServiceMappingResponse,
  ServiceEdgeResponse,
  MapStatusItem,
  HierarchyEdge,
} from "@/types";

const nodeTypes = { service: ServiceNode };

const NODE_W = 220;
const NODE_GAP = 40;
const LEVEL_GAP = 180;

interface Props {
  projectId: string;
  mappings: ServiceMappingResponse[];
  edges: ServiceEdgeResponse[];
  statusItems: MapStatusItem[];
  hierarchyEdges: HierarchyEdge[];
  onNodeClick: (mappingId: string) => void;
  onRefresh: () => void;
  readOnly?: boolean;
}

function findParentDeployment(
  mappings: ServiceMappingResponse[],
  repoName: string,
): ServiceMappingResponse | null {
  const repoLower = repoName.toLowerCase();
  return (
    mappings.find((m) => {
      const dep = m.deployment_name.toLowerCase();
      return dep === repoLower || dep.startsWith(repoLower + "-");
    }) ?? null
  );
}

interface DeploymentTree {
  parent: ServiceMappingResponse;
  children: { mapping: ServiceMappingResponse; edgeLabel: string }[];
}

/**
 * Build the tree in three phases:
 *   1. **Structure** from context-source grouping + repo name matching
 *   2. **Orphan adoption** – groups with no parent deployment get merged
 *      into an existing tree via hierarchy edges or namespace matching
 *   3. **Label upgrade** from server-computed hierarchy edges
 */
function buildTree(
  mappings: ServiceMappingResponse[],
  hierarchyEdges: HierarchyEdge[],
): {
  trees: DeploymentTree[];
  standalone: ServiceMappingResponse[];
} {
  // Phase 1: build initial trees from context-source grouping
  const bySource = new Map<string, ServiceMappingResponse[]>();
  const noSource: ServiceMappingResponse[] = [];

  for (const m of mappings) {
    if (m.is_infrastructure || !m.context_source_id) {
      noSource.push(m);
      continue;
    }
    const key = String(m.context_source_id);
    if (!bySource.has(key)) bySource.set(key, []);
    bySource.get(key)!.push(m);
  }

  const trees: DeploymentTree[] = [];
  const orphanGroups: ServiceMappingResponse[][] = [];

  for (const [, group] of bySource) {
    const repoName = group[0]?.context_source_name ?? "";
    const parent = findParentDeployment(group, repoName);

    if (parent) {
      trees.push({
        parent,
        children: group
          .filter((m) => m.id !== parent.id)
          .map((m) => ({ mapping: m, edgeLabel: "managedBy" })),
      });
    } else {
      orphanGroups.push(group);
    }
  }

  // Phase 2: adopt orphan groups into existing trees
  const depLookup = new Map<string, ServiceMappingResponse>();
  for (const m of mappings) {
    depLookup.set(`${m.deployment_name}|${m.deployment_namespace}`, m);
  }

  // hierarchy: child deployment key → { parentKey, label, relationship }
  const hierChild = new Map<
    string,
    { parentKey: string; label: string; relationship: string }
  >();
  for (const edge of hierarchyEdges) {
    const ck = `${edge.child_name}|${edge.child_namespace}`;
    const pk = `${edge.parent_name}|${edge.parent_namespace}`;
    hierChild.set(ck, {
      parentKey: pk,
      label: edge.label,
      relationship: edge.relationship,
    });
  }

  const treeParentKeys = new Set(
    trees.map(
      (t) => `${t.parent.deployment_name}|${t.parent.deployment_namespace}`,
    ),
  );

  // Index: namespace → tree index (for namespace-based fallback)
  const nsToTree = new Map<string, number>();
  for (let i = 0; i < trees.length; i++) {
    for (const c of trees[i].children) {
      nsToTree.set(c.mapping.deployment_namespace, i);
    }
  }

  const stillOrphan: ServiceMappingResponse[] = [];

  for (const group of orphanGroups) {
    let adoptedTreeIdx = -1;

    // Strategy A: use hierarchy edges to find a parent tree
    if (hierChild.size > 0) {
      for (const m of group) {
        const ck = `${m.deployment_name}|${m.deployment_namespace}`;
        const info = hierChild.get(ck);
        if (info && treeParentKeys.has(info.parentKey)) {
          adoptedTreeIdx = trees.findIndex(
            (t) =>
              `${t.parent.deployment_name}|${t.parent.deployment_namespace}` ===
              info.parentKey,
          );
          break;
        }
      }
    }

    // Strategy B: namespace-based fallback – if all orphans share a
    // namespace with children in an existing tree, adopt them there
    if (adoptedTreeIdx < 0 && trees.length > 0) {
      const namespaces = new Set(group.map((m) => m.deployment_namespace));
      const candidates = new Set<number>();
      for (const ns of namespaces) {
        const idx = nsToTree.get(ns);
        if (idx !== undefined) candidates.add(idx);
      }
      if (candidates.size === 1) {
        adoptedTreeIdx = [...candidates][0];
      }
    }

    if (adoptedTreeIdx >= 0) {
      const tree = trees[adoptedTreeIdx];
      const existingIds = new Set([
        tree.parent.id,
        ...tree.children.map((c) => c.mapping.id),
      ]);
      for (const m of group) {
        if (!existingIds.has(m.id)) {
          tree.children.push({ mapping: m, edgeLabel: "managedBy" });
        }
      }
    } else {
      stillOrphan.push(...group);
    }
  }

  const standalone: ServiceMappingResponse[] = [...noSource, ...stillOrphan];

  // Phase 3: upgrade edge labels using hierarchy data
  if (hierChild.size > 0) {
    const hierarchyLabel = new Map<string, string>();
    for (const [ck, info] of hierChild) {
      const childMapping = depLookup.get(ck);
      if (!childMapping) continue;
      const prefix = info.relationship === "direct" ? "" : "indirect: ";
      hierarchyLabel.set(childMapping.id, `${prefix}${info.label}`);
    }

    for (const tree of trees) {
      for (const child of tree.children) {
        const label = hierarchyLabel.get(child.mapping.id);
        if (label) child.edgeLabel = label;
      }
    }
  }

  return { trees, standalone };
}

function makeServiceNode(
  m: ServiceMappingResponse,
  statusMap: Map<string, MapStatusItem>,
  x: number,
  y: number,
): Node {
  const st = statusMap.get(m.id);
  const dep = st?.deployment;
  const gap = st?.gap;

  return {
    id: m.id,
    type: "service",
    position: { x, y },
    data: {
      label: m.deployment_name,
      namespace: m.deployment_namespace,
      status: dep?.status ?? "failing",
      replicas: dep?.replicas ?? 0,
      readyReplicas: dep?.ready_replicas ?? 0,
      gapCount: gap?.gap_count ?? null,
      gapStatus: gap?.status ?? "unknown",
      repoName: m.context_source_name,
      isInfrastructure: m.is_infrastructure,
    },
  };
}

function makeEdge(
  parentId: string,
  childId: string,
  label: string,
): Edge {
  const isDirect = !label.startsWith("indirect") && label !== "managedBy";
  const isIndirect = label.startsWith("indirect");
  const color = isDirect
    ? "var(--o-success, #22c55e)"
    : isIndirect
      ? "var(--o-warning, #f59e0b)"
      : "var(--o-accent)";
  return {
    id: `e-${parentId}-${childId}`,
    source: parentId,
    target: childId,
    label,
    type: "smoothstep",
    animated: true,
    style: { stroke: color, strokeWidth: isDirect ? 2 : 1.5 },
    labelStyle: { fontSize: 9, fill: "var(--o-text-secondary)", fontWeight: 500 },
    labelBgStyle: { fill: "var(--o-bg)", fillOpacity: 0.85 },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 12,
      height: 12,
      color,
    },
  };
}

function buildNodesAndEdges(
  mappings: ServiceMappingResponse[],
  statusItems: MapStatusItem[],
  hierarchyEdges: HierarchyEdge[],
): { nodes: Node[]; edges: Edge[] } {
  const statusMap = new Map(statusItems.map((s) => [s.mapping_id, s]));
  const { trees, standalone } = buildTree(mappings, hierarchyEdges);

  const nodes: Node[] = [];
  const edges: Edge[] = [];

  let globalOffsetX = 0;

  for (const tree of trees) {
    const childCount = tree.children.length;
    const groupWidth = Math.max(childCount, 1) * (NODE_W + NODE_GAP) - NODE_GAP;
    const parentX = globalOffsetX + groupWidth / 2 - NODE_W / 2;

    nodes.push(makeServiceNode(tree.parent, statusMap, parentX, 0));

    tree.children.forEach((child, idx) => {
      const x = globalOffsetX + idx * (NODE_W + NODE_GAP);
      nodes.push(makeServiceNode(child.mapping, statusMap, x, LEVEL_GAP));
      edges.push(makeEdge(tree.parent.id, child.mapping.id, child.edgeLabel));
    });

    globalOffsetX += groupWidth + 120;
  }

  if (standalone.length > 0) {
    const orphanY = trees.length > 0 ? LEVEL_GAP * 2 + 40 : 0;
    standalone.forEach((m, idx) => {
      nodes.push(
        makeServiceNode(m, statusMap, globalOffsetX + idx * (NODE_W + NODE_GAP), orphanY),
      );
    });
  }

  return { nodes, edges };
}

export default function MapCanvas({
  projectId,
  mappings,
  statusItems,
  hierarchyEdges,
  onNodeClick,
  onRefresh,
}: Props) {
  const { nodes: initNodes, edges: initEdges } = useMemo(
    () => buildNodesAndEdges(mappings, statusItems, hierarchyEdges),
    [mappings, statusItems, hierarchyEdges],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initNodes);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState(initEdges);

  useEffect(() => {
    const result = buildNodesAndEdges(mappings, statusItems, hierarchyEdges);
    setNodes(result.nodes);
    setFlowEdges(result.edges);
  }, [mappings, statusItems, hierarchyEdges, setNodes, setFlowEdges]);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick(node.id);
    },
    [onNodeClick],
  );

  return (
    <div className="relative h-[600px] w-full overflow-hidden rounded-xl border border-[var(--o-border)]">
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        panOnDrag
        zoomOnScroll
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={3}
          pannable
          zoomable
          style={{
            backgroundColor: "var(--o-bg)",
            border: "1px solid var(--o-border)",
            borderRadius: 8,
          }}
        />
        <Panel position="top-right" className="flex gap-1.5">
          <button
            type="button"
            className="o-btn-ghost flex items-center gap-1 text-xs"
            onClick={onRefresh}
          >
            <RefreshCw className="h-3 w-3" />
            Refresh
          </button>
        </Panel>
      </ReactFlow>
    </div>
  );
}
