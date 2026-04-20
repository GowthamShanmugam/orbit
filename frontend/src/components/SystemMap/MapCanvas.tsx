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
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ServiceNode from "./ServiceNode";
import type { ServiceMappingResponse } from "@/types";

const nodeTypes = { service: ServiceNode };

const NODE_W = 220;
const NODE_GAP = 40;
const LEVEL_GAP = 180;

interface Props {
  mappings: ServiceMappingResponse[];
  onNodeClick: (mappingId: string) => void;
}

interface DeploymentTree {
  parent: ServiceMappingResponse;
  children: ServiceMappingResponse[];
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

function buildTree(mappings: ServiceMappingResponse[]): {
  trees: DeploymentTree[];
  standalone: ServiceMappingResponse[];
} {
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
        children: group.filter((m) => m.id !== parent.id),
      });
    } else {
      orphanGroups.push(group);
    }
  }

  // Adopt orphan groups into existing trees by namespace
  const nsToTree = new Map<string, number>();
  for (let i = 0; i < trees.length; i++) {
    for (const c of trees[i].children) {
      nsToTree.set(c.deployment_namespace, i);
    }
  }

  const stillOrphan: ServiceMappingResponse[] = [];

  for (const group of orphanGroups) {
    const namespaces = new Set(group.map((m) => m.deployment_namespace));
    const candidates = new Set<number>();
    for (const ns of namespaces) {
      const idx = nsToTree.get(ns);
      if (idx !== undefined) candidates.add(idx);
    }

    if (candidates.size === 1) {
      const tree = trees[[...candidates][0]];
      const existingIds = new Set([
        tree.parent.id,
        ...tree.children.map((c) => c.id),
      ]);
      for (const m of group) {
        if (!existingIds.has(m.id)) tree.children.push(m);
      }
    } else {
      stillOrphan.push(...group);
    }
  }

  return { trees, standalone: [...noSource, ...stillOrphan] };
}

function makeServiceNode(m: ServiceMappingResponse, x: number, y: number): Node {
  return {
    id: m.id,
    type: "service",
    position: { x, y },
    data: {
      label: m.deployment_name,
      namespace: m.deployment_namespace,
      repoName: m.context_source_name,
      isInfrastructure: m.is_infrastructure,
    },
  };
}

function makeEdge(parentId: string, childId: string): Edge {
  return {
    id: `e-${parentId}-${childId}`,
    source: parentId,
    target: childId,
    type: "smoothstep",
    animated: true,
    style: { stroke: "var(--o-accent)", strokeWidth: 1.5 },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 12,
      height: 12,
      color: "var(--o-accent)",
    },
  };
}

function buildNodesAndEdges(mappings: ServiceMappingResponse[]): {
  nodes: Node[];
  edges: Edge[];
} {
  const { trees, standalone } = buildTree(mappings);
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  let globalOffsetX = 0;

  for (const tree of trees) {
    const childCount = tree.children.length;
    const groupWidth = Math.max(childCount, 1) * (NODE_W + NODE_GAP) - NODE_GAP;
    const parentX = globalOffsetX + groupWidth / 2 - NODE_W / 2;

    nodes.push(makeServiceNode(tree.parent, parentX, 0));

    tree.children.forEach((child, idx) => {
      const x = globalOffsetX + idx * (NODE_W + NODE_GAP);
      nodes.push(makeServiceNode(child, x, LEVEL_GAP));
      edges.push(makeEdge(tree.parent.id, child.id));
    });

    globalOffsetX += groupWidth + 120;
  }

  if (standalone.length > 0) {
    const orphanY = trees.length > 0 ? LEVEL_GAP * 2 + 40 : 0;
    standalone.forEach((m, idx) => {
      nodes.push(
        makeServiceNode(m, globalOffsetX + idx * (NODE_W + NODE_GAP), orphanY),
      );
    });
  }

  return { nodes, edges };
}

export default function MapCanvas({ mappings, onNodeClick }: Props) {
  const { nodes: initNodes, edges: initEdges } = useMemo(
    () => buildNodesAndEdges(mappings),
    [mappings],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initNodes);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState(initEdges);

  useEffect(() => {
    const result = buildNodesAndEdges(mappings);
    setNodes(result.nodes);
    setFlowEdges(result.edges);
  }, [mappings, setNodes, setFlowEdges]);

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
      </ReactFlow>
    </div>
  );
}
