import { useSearchParams } from 'react-router-dom';
import type { ProjectWorkspace } from '../api/types';
import { useI18n } from '../i18n';

type Graph = NonNullable<ProjectWorkspace['process_graph']>;

// Column x per layer, row y per node inside a layer. This is a plain layered view, not an
// automatic-layout solver: it only reflects the edges the revision already declares.
const NODE_W = 160, NODE_H = 72, GAP_X = 48, GAP_Y = 24, PAD = 16;

function layersOf(graph: Graph): string[][] {
  const incoming = new Map(graph.nodes.map(n => [n.id, new Set<string>()]));
  for (const edge of graph.edges) incoming.get(edge.target)?.add(edge.source);
  const depth = new Map<string, number>();
  const resolve = (id: string, seen: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0; // cycle guard: never hang on a malformed graph
    seen.add(id);
    const parents = [...(incoming.get(id) ?? [])].map(p => resolve(p, seen));
    const value = parents.length ? 1 + Math.max(...parents) : 0;
    depth.set(id, value);
    return value;
  };
  graph.nodes.forEach(n => resolve(n.id, new Set()));
  const columns: string[][] = [];
  for (const node of graph.nodes) {
    const layer = depth.get(node.id) ?? 0;
    (columns[layer] ??= []).push(node.id);
  }
  return columns;
}

export function ProcessGraph({ graph }: { graph: Graph }) {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const selected = params.get('process') ?? graph.nodes[0]?.id;
  const columns = layersOf(graph);
  const position = new Map<string, { x: number; y: number }>();
  columns.forEach((ids, layer) => ids.forEach((id, row) =>
    position.set(id, { x: PAD + layer * (NODE_W + GAP_X), y: PAD + row * (NODE_H + GAP_Y) })));
  const width = PAD * 2 + columns.length * NODE_W + Math.max(0, columns.length - 1) * GAP_X;
  const height = PAD * 2 + Math.max(0, ...columns.map(c => c.length)) * (NODE_H + GAP_Y) - GAP_Y;
  const center = (id: string) => { const p = position.get(id)!; return { x: p.x + NODE_W / 2, y: p.y + NODE_H / 2 }; };
  const pick = (id: string) => setParams(prev => { const p = new URLSearchParams(prev); p.set('process', id); return p; });
  return (
    <div className="process-graph" role="group" aria-label={t('process.graphAria')}>
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} className="process-graph-svg" tabIndex={0}>
        {graph.edges.map((edge, i) => {
          const a = center(edge.source), b = center(edge.target);
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="process-graph-edge" />;
        })}
        {graph.nodes.map(node => {
          const p = position.get(node.id)!;
          const isSel = node.id === selected;
          return (
            <g key={node.id} transform={`translate(${p.x},${p.y})`} className={`process-graph-node${isSel ? ' is-selected' : ''}`}
               role="button" tabIndex={0} aria-pressed={isSel} aria-label={node.name}
               onClick={() => pick(node.id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(node.id); } }}>
              <rect width={NODE_W} height={NODE_H} rx={6} />
              <foreignObject width={NODE_W} height={NODE_H}>
                <div className="process-graph-label" title={node.name}>{node.name}</div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
