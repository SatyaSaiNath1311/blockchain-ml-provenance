import { useEffect, useState } from 'react';
import { Database, GitBranch, ChevronRight, Layers } from 'lucide-react';
import { listDatasets, getDatasetVersions, getLineage } from '../api/client';
import { SkeletonCard, SkeletonRows } from '../components/Skeleton';
import EmptyState from '../components/EmptyState';
import ErrorAlert from '../components/ErrorAlert';

/* ── Lineage SVG ──────────────────────────────────────────── */
function LineageSVG({ nodes }) {
  if (!nodes || nodes.length === 0) return null;
  const BOX_W = 220, BOX_H = 52, GAP_X = 60, PAD = 20;
  const n = nodes.length;
  const svgW = n * BOX_W + (n - 1) * GAP_X + PAD * 2;
  const svgH = BOX_H + PAD * 2;

  return (
    <div className="lineage-svg-wrap">
      <svg width={svgW} height={svgH} role="img" aria-label="Lineage graph">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--clr-accent)" />
          </marker>
        </defs>
        {nodes.map((node, i) => {
          const x = PAD + i * (BOX_W + GAP_X);
          const y = PAD;
          const isLast = i === n - 1;
          return (
            <g key={node.version_id ?? i}>
              {/* Arrow from previous box */}
              {i > 0 && (
                <line
                  x1={x - GAP_X}
                  y1={y + BOX_H / 2}
                  x2={x}
                  y2={y + BOX_H / 2}
                  stroke="var(--clr-accent)"
                  strokeWidth="1.5"
                  markerEnd="url(#arrow)"
                />
              )}
              {/* Box */}
              <rect
                x={x} y={y}
                width={BOX_W} height={BOX_H}
                rx="6"
                fill={isLast ? 'var(--clr-accent-dim)' : 'var(--clr-surface-3)'}
                stroke={isLast ? 'var(--clr-accent)' : 'var(--clr-border)'}
                strokeWidth="1"
              />
              {/* Op type label */}
              <text
                x={x + BOX_W / 2} y={y + 20}
                textAnchor="middle"
                fill="var(--clr-text)"
                fontSize="11"
                fontWeight="600"
                fontFamily="Inter,sans-serif"
              >
                {node.operation_type ?? 'ingest'}
              </text>
              {/* Short version ID */}
              <text
                x={x + BOX_W / 2} y={y + 36}
                textAnchor="middle"
                fill="var(--clr-text-3)"
                fontSize="9"
                fontFamily="JetBrains Mono,monospace"
              >
                {String(node.version_id ?? '').slice(0, 8)}…
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ── Version list ─────────────────────────────────────────── */
function VersionList({ datasetId, onSelectVersion }) {
  const [versions, setVersions] = useState(null);
  const [lineage, setLineage] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');
  const [lineageError, setLineageError] = useState('');

  useEffect(() => {
    setVersions(null);
    setLineage(null);
    setSelected(null);
    setError('');
    getDatasetVersions(datasetId)
      .then(setVersions)
      .catch((e) => setError(e.message));
  }, [datasetId]);

  const loadLineage = (vId) => {
    setSelected(vId);
    setLineage(null);
    setLineageError('');
    if (onSelectVersion) onSelectVersion(vId);
    getLineage(vId)
      .then(setLineage)
      .catch((e) => setLineageError(e.message));
  };

  if (error) return <ErrorAlert message={error} />;
  if (!versions) return <SkeletonRows n={3} />;
  if (versions.length === 0) return <EmptyState title="No versions" />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Version ID</th>
              <th>Operation</th>
              <th>Chunks</th>
              <th>Timestamp</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version_id} style={{ cursor: 'pointer' }} onClick={() => loadLineage(v.version_id)}>
                <td className="mono" style={{ fontSize: '.72rem' }}>{v.version_id?.slice(0, 12)}…</td>
                <td>
                  <span className="badge badge-neutral">{v.operation_type ?? '—'}</span>
                </td>
                <td>{v.num_chunks ?? '—'}</td>
                <td className="text-xs text-faint">
                  {v.timestamp ? new Date(Number(v.timestamp) * 1000).toLocaleString() : '—'}
                </td>
                <td>
                  <ChevronRight size={14} style={{ color: 'var(--clr-text-3)' }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="card" style={{ padding: 'var(--sp-4)' }}>
          <div className="flex items-center gap-2 mb-4">
            <GitBranch size={15} style={{ color: 'var(--clr-accent)' }} />
            <span className="text-sm" style={{ fontWeight: 600 }}>Lineage</span>
            <span className="hash" style={{ fontSize: '.65rem' }}>{selected}</span>
          </div>
          {lineageError && <ErrorAlert message={lineageError} />}
          {!lineage && !lineageError && <SkeletonRows n={1} />}
          {lineage && <LineageSVG nodes={lineage} />}
        </div>
      )}
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────── */
export default function ExplorerPage() {
  const [datasets, setDatasets] = useState(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    listDatasets()
      .then(setDatasets)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Dataset Explorer</h1>
        <p className="page-desc">Browse datasets, version history, and lineage graphs.</p>
      </div>

      <div style={{ display: 'flex', gap: 'var(--sp-4)', flexDirection: 'column' }}>
        {/* Dataset list */}
        <div className="card">
          <div className="card-header">
            <Database size={18} style={{ color: 'var(--clr-accent)' }} />
            <p className="card-title">Datasets</p>
          </div>
          <ErrorAlert message={error} />
          {!datasets && !error && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {[1, 2, 3].map((i) => <SkeletonCard key={i} />)}
            </div>
          )}
          {datasets?.length === 0 && (
            <EmptyState
              icon={Database}
              title="No datasets yet"
              desc="Upload a CSV to get started."
            />
          )}
          {datasets && datasets.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Dataset ID</th>
                    <th>Filename</th>
                    <th>Size</th>
                    <th>Created</th>
                    <th>Versions</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((ds) => (
                    <tr
                      key={ds.dataset_id}
                      style={{ cursor: 'pointer', background: selected === ds.dataset_id ? 'var(--clr-accent-dim)' : '' }}
                      onClick={() => setSelected(ds.dataset_id === selected ? null : ds.dataset_id)}
                    >
                      <td className="mono" style={{ fontSize: '.72rem' }}>{ds.dataset_id?.slice(0, 12)}…</td>
                      <td>{ds.filename}</td>
                      <td className="text-xs">{ds.size_bytes ? `${(ds.size_bytes / 1024).toFixed(1)} KB` : '—'}</td>
                      <td className="text-xs text-faint">
                        {ds.created_at ? new Date(ds.created_at).toLocaleDateString() : '—'}
                      </td>
                      <td>
                        <span className="badge badge-neutral">
                          <Layers size={11} /> {ds.version_count}
                        </span>
                      </td>
                      <td>
                        <ChevronRight size={14} style={{ color: 'var(--clr-text-3)' }} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Version list + lineage */}
        {selected && (
          <div className="card">
            <div className="card-header">
              <Layers size={18} style={{ color: 'var(--clr-accent)' }} />
              <p className="card-title">Versions</p>
              <span className="hash" style={{ fontSize: '.65rem', marginLeft: 'auto' }}>{selected}</span>
            </div>
            <VersionList datasetId={selected} />
          </div>
        )}
      </div>
    </div>
  );
}
