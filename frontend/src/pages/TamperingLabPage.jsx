import { useEffect, useState } from 'react';
import { FlaskConical, ShieldAlert, Lock } from 'lucide-react';
import { listDatasets, getDatasetVersions, tamperDemo } from '../api/client';
import VerifyResult from '../components/VerifyResult';
import ErrorAlert from '../components/ErrorAlert';
import { SkeletonRows } from '../components/Skeleton';
import EmptyState from '../components/EmptyState';
import ShortId from '../components/ShortId';

const ATTACKS_WITH_FRACTION = [
  'modify_cells', 'delete_rows', 'insert_rows', 'flip_labels', 'modify_preprocessing_output',
];
const ATTACKS_NO_FRACTION = ['swap_columns', 'replace_file'];
const ALL_ATTACKS = [...ATTACKS_WITH_FRACTION, ...ATTACKS_NO_FRACTION];
const FRACTIONS = [0.001, 0.01, 0.1];
const FRACTION_LABELS = { 0.001: '0.1%', 0.01: '1%', 0.1: '10%' };

const ATTACK_DESCRIPTIONS = {
  modify_cells: 'Modifies random cell values in existing rows without changing row count or column schema.',
  delete_rows: 'Removes a random subset of data rows, shifting subsequent row and chunk boundaries.',
  insert_rows: 'Inserts fabricated rows at random positions, shifting subsequent row and chunk boundaries.',
  flip_labels: 'Flips binary classification target labels (0 ↔ 1) to simulate data poisoning attacks.',
  modify_preprocessing_output: 'Alters computed preprocessing output without updating the recorded transformation pipeline.',
  swap_columns: 'Permutes two column headers and their contents to break feature schema alignment.',
  replace_file: 'Substitutes the entire dataset with a completely different file.',
};

function getOperationLabel(v) {
  if (
    v.operation_type === 'preprocess' ||
    v.operation_type === 'preprocess_clean' ||
    (v.parent_version_id && v.parent_version_id !== '00000000-0000-0000-0000-000000000000')
  ) {
    return 'Cleaned version';
  }
  return 'Original upload';
}

export default function TamperingLabPage() {
  const [datasets, setDatasets] = useState(null);
  const [dsError, setDsError] = useState('');
  const [selectedDs, setSelectedDs] = useState('');
  const [versions, setVersions] = useState(null);
  const [verError, setVerError] = useState('');
  const [selectedVer, setSelectedVer] = useState('');

  const [attack, setAttack] = useState('modify_cells');
  const [fraction, setFraction] = useState(0.01);
  const [seed, setSeed] = useState(42);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const needsFraction = ATTACKS_WITH_FRACTION.includes(attack);

  useEffect(() => {
    listDatasets()
      .then(setDatasets)
      .catch((e) => setDsError(e.message));
  }, []);

  const handleDatasetChange = (dsId) => {
    setSelectedDs(dsId);
    setVersions(null);
    setSelectedVer('');
    setResult(null);
    setVerError('');
  };

  useEffect(() => {
    if (!selectedDs) return;
    let cancelled = false;
    getDatasetVersions(selectedDs)
      .then((verList) => {
        if (!cancelled) {
          setVersions(verList);
          // Auto-select when a dataset has only one version
          if (verList && verList.length === 1) {
            setSelectedVer(verList[0].version_id);
          }
        }
      })
      .catch((e) => {
        if (!cancelled) setVerError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDs]);

  const run = async () => {
    if (!selectedVer) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await tamperDemo(selectedVer, attack, needsFraction ? fraction : null, seed);
      setResult(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  // Sort datasets newest first
  const sortedDatasets = [...(datasets || [])].sort((a, b) => {
    const tA = a.created_at ? new Date(a.created_at).getTime() : 0;
    const tB = b.created_at ? new Date(b.created_at).getTime() : 0;
    return tB - tA;
  });

  return (
    <div className="page-container">
      <div className="page-header">
        <h1 className="page-title">Tampering lab</h1>
        <p className="page-desc">
          Simulate controlled attacks on a temporary copy of a dataset and observe cryptographic detection results.
        </p>
      </div>

      <div className="page-2col-split">
        {/* Left Column: Controls and safety info */}
        <div>
          {/* Safety notice */}
          <div className="alert alert-info mb-4">
            <Lock size={16} style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <strong>The original stored file is never modified.</strong>
              {' '}The attack is applied to an isolated temporary copy which is deleted immediately after
              verification. Your on-chain record and stored data remain intact.
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <FlaskConical size={18} style={{ color: 'var(--clr-warn)' }} />
              <div>
                <p className="card-title">Configure attack simulation</p>
                <p className="card-sub">Select dataset version and parameterize the simulated attack</p>
              </div>
            </div>

            {/* Dataset picker */}
            <div className="form-group mb-3">
              <label htmlFor="lab-ds">Dataset</label>
              <ErrorAlert message={dsError} />
              {!datasets && !dsError && <SkeletonRows n={1} />}
              {datasets && (
                <select
                  id="lab-ds"
                  value={selectedDs}
                  onChange={(e) => handleDatasetChange(e.target.value)}
                >
                  <option value="">— choose dataset —</option>
                  {sortedDatasets.map((d) => {
                    const dateStr = d.created_at ? new Date(d.created_at).toLocaleDateString() : 'recent';
                    const vCount = d.version_count || 1;
                    const vText = `${vCount} ${vCount === 1 ? 'version' : 'versions'}`;
                    return (
                      <option key={d.dataset_id} value={d.dataset_id}>
                        {d.filename || 'dataset.csv'} • {dateStr} • {vText}
                      </option>
                    );
                  })}
                </select>
              )}
              {datasets?.length === 0 && (
                <EmptyState
                  title="No datasets yet"
                  desc="Upload and anchor a CSV dataset before simulating tampering attacks."
                  actionLabel="Upload and anchor dataset"
                  actionHref="/"
                />
              )}
            </div>

            {/* Version picker */}
            {selectedDs && (
              <div className="form-group mb-3">
                <label htmlFor="lab-ver">Version</label>
                <ErrorAlert message={verError} />
                {!versions && !verError && <SkeletonRows n={1} />}
                {versions && (
                  <select
                    id="lab-ver"
                    value={selectedVer}
                    onChange={(e) => {
                      setSelectedVer(e.target.value);
                      setResult(null);
                    }}
                  >
                    <option value="">— choose version —</option>
                    {versions.map((v) => {
                      const op = getOperationLabel(v);
                      return (
                        <option key={v.version_id} value={v.version_id}>
                          {op} — {v.version_id.slice(0, 8)}… ({v.num_chunks ?? '—'} chunks)
                        </option>
                      );
                    })}
                  </select>
                )}
                {versions?.length === 0 && (
                  <EmptyState
                    title="No versions recorded"
                    desc="This dataset currently has no recorded versions on-chain."
                    actionLabel="Upload new version"
                    actionHref="/"
                  />
                )}
              </div>
            )}

            {/* Attack type */}
            {selectedVer && (
              <>
                <div className="form-group mb-3">
                  <label htmlFor="lab-attack">Attack type</label>
                  <select
                    id="lab-attack"
                    value={attack}
                    onChange={(e) => setAttack(e.target.value)}
                  >
                    {ALL_ATTACKS.map((a) => (
                      <option key={a} value={a}>{a.replace(/_/g, ' ')}</option>
                    ))}
                  </select>
                  <p className="text-xs text-muted mt-1" style={{ lineHeight: 1.4 }}>
                    {ATTACK_DESCRIPTIONS[attack]}
                  </p>
                </div>

                {needsFraction && (
                  <div className="form-group mb-3">
                    <label>Fraction of rows affected</label>
                    <div className="flex gap-2">
                      {FRACTIONS.map((f) => (
                        <button
                          key={f}
                          type="button"
                          id={`fraction-${f}`}
                          className={`btn ${fraction === f ? 'btn-primary' : 'btn-ghost'} btn-sm`}
                          onClick={() => setFraction(f)}
                        >
                          {FRACTION_LABELS[f]}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className="form-group mb-4">
                  <label htmlFor="lab-seed">Random seed</label>
                  <input
                    id="lab-seed"
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value))}
                    style={{ maxWidth: 120 }}
                  />
                </div>

                <button
                  type="button"
                  id="run-attack-btn"
                  className="btn btn-danger btn-lg"
                  disabled={loading}
                  onClick={run}
                >
                  <ShieldAlert size={16} />
                  {loading ? 'Running attack…' : 'Run attack on a copy'}
                </button>
              </>
            )}

            <ErrorAlert message={error} />
          </div>
        </div>

        {/* Right Column: Results */}
        <div>
          {result ? (
            <div>
              {/* Attack details */}
              <div className="card mb-4" style={{ padding: 'var(--sp-5)' }}>
                <div className="card-header" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                    <FlaskConical size={18} style={{ color: 'var(--clr-warn)' }} />
                    <p className="card-title">Attack details (temporary copy only)</p>
                  </div>
                  <div style={{ marginLeft: 'auto', paddingRight: 'var(--sp-3)' }}>
                    <ShortId id={selectedVer} length={12} />
                  </div>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-2)' }}>
                  {Object.entries(result.attack_details ?? {}).map(([k, v]) => (
                    <div key={k} className="badge badge-warn">
                      {k}: {Array.isArray(v) ? `[${v.slice(0, 5).join(', ')}${v.length > 5 ? '…' : ''}]` : String(v)}
                    </div>
                  ))}
                </div>
                {result.original_file_preserved && (
                  <div className="alert alert-success mt-3" style={{ fontSize: 'var(--text-sm)', padding: 'var(--sp-3) var(--sp-4)' }}>
                    <Lock size={14} style={{ flexShrink: 0 }} />
                    Original file confirmed preserved — SHA-256 hash unchanged on disk.
                  </div>
                )}
              </div>

              {/* Verify result */}
              <VerifyResult result={result.verify_result} />
            </div>
          ) : (
            <div className="card" style={{ borderStyle: 'dashed', textAlign: 'center', padding: 'var(--sp-8) var(--sp-6)' }}>
              <FlaskConical size={36} style={{ color: 'var(--clr-text-3)', margin: '0 auto var(--sp-3)' }} />
              <p className="card-title" style={{ fontSize: '1rem', color: 'var(--clr-text-2)' }}>No attack simulation active</p>
              <p className="text-xs text-muted" style={{ maxWidth: 360, margin: 'var(--sp-2) auto 0' }}>
                Select a dataset version and attack type on the left, then run the simulation on an isolated copy to observe Merkle tree mismatch localization.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
