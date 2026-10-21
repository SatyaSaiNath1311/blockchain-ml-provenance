import { useEffect, useState } from 'react';
import { FlaskConical, ShieldAlert, Lock } from 'lucide-react';
import { listDatasets, getDatasetVersions, tamperDemo } from '../api/client';
import VerifyResult from '../components/VerifyResult';
import ErrorAlert from '../components/ErrorAlert';
import { SkeletonRows } from '../components/Skeleton';
import EmptyState from '../components/EmptyState';

const ATTACKS_WITH_FRACTION = [
  'modify_cells', 'delete_rows', 'insert_rows', 'flip_labels', 'modify_preprocessing_output',
];
const ATTACKS_NO_FRACTION = ['swap_columns', 'replace_file'];
const ALL_ATTACKS = [...ATTACKS_WITH_FRACTION, ...ATTACKS_NO_FRACTION];
const FRACTIONS = [0.001, 0.01, 0.1];
const FRACTION_LABELS = { 0.001: '0.1%', 0.01: '1%', 0.1: '10%' };

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

  useEffect(() => {
    if (!selectedDs) { setVersions(null); setSelectedVer(''); return; }
    setVersions(null);
    setVerError('');
    setSelectedVer('');
    setResult(null);
    getDatasetVersions(selectedDs)
      .then(setVersions)
      .catch((e) => setVerError(e.message));
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

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Tampering Lab</h1>
        <p className="page-desc">
          Simulate controlled attacks on a temp copy of a dataset and observe detection results.
        </p>
      </div>

      {/* Safety notice */}
      <div className="alert alert-info mb-4" style={{ maxWidth: 640 }}>
        <Lock size={16} style={{ flexShrink: 0, marginTop: 2 }} />
        <div>
          <strong>The original stored file is never modified.</strong>
          {' '}The attack is applied to an isolated temporary copy which is deleted immediately after
          verification. Your on-chain record and stored data remain intact.
        </div>
      </div>

      <div className="card" style={{ maxWidth: 640 }}>
        <div className="card-header">
          <FlaskConical size={18} style={{ color: 'var(--clr-warn)' }} />
          <p className="card-title">Configure attack</p>
        </div>

        {/* Dataset picker */}
        <div className="form-group mb-3">
          <label htmlFor="lab-ds">Dataset</label>
          <ErrorAlert message={dsError} />
          {!datasets && !dsError && <SkeletonRows n={1} />}
          {datasets && (
            <select id="lab-ds" value={selectedDs} onChange={(e) => setSelectedDs(e.target.value)}>
              <option value="">— choose dataset —</option>
              {datasets.map((d) => (
                <option key={d.dataset_id} value={d.dataset_id}>
                  {d.filename} ({d.dataset_id.slice(0, 8)}…)
                </option>
              ))}
            </select>
          )}
          {datasets?.length === 0 && <EmptyState title="No datasets yet" />}
        </div>

        {/* Version picker */}
        {selectedDs && (
          <div className="form-group mb-3">
            <label htmlFor="lab-ver">Version</label>
            <ErrorAlert message={verError} />
            {!versions && !verError && <SkeletonRows n={1} />}
            {versions && (
              <select id="lab-ver" value={selectedVer} onChange={(e) => { setSelectedVer(e.target.value); setResult(null); }}>
                <option value="">— choose version —</option>
                {versions.map((v) => (
                  <option key={v.version_id} value={v.version_id}>
                    {v.operation_type ?? 'ingest'} — {v.version_id.slice(0, 8)}…
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {/* Attack type */}
        {selectedVer && (
          <>
            <div className="form-group mb-3">
              <label htmlFor="lab-attack">Attack type</label>
              <select id="lab-attack" value={attack} onChange={(e) => setAttack(e.target.value)}>
                {ALL_ATTACKS.map((a) => (
                  <option key={a} value={a}>{a.replace(/_/g, ' ')}</option>
                ))}
              </select>
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
              {loading ? 'Running attack…' : 'Run attack & verify'}
            </button>
          </>
        )}

        <ErrorAlert message={error} />
      </div>

      {/* Results */}
      {result && (
        <div className="mt-6" style={{ maxWidth: 760 }}>
          {/* Attack details */}
          <div className="card mb-4" style={{ padding: 'var(--sp-4)' }}>
            <div className="card-header">
              <FlaskConical size={16} style={{ color: 'var(--clr-warn)' }} />
              <p className="card-title">Attack details (temp copy only)</p>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-2)' }}>
              {Object.entries(result.attack_details ?? {}).map(([k, v]) => (
                <div key={k} className="badge badge-warn">
                  {k}: {Array.isArray(v) ? `[${v.slice(0, 5).join(', ')}${v.length > 5 ? '…' : ''}]` : String(v)}
                </div>
              ))}
            </div>
            {result.original_file_preserved && (
              <div className="alert alert-success mt-3">
                <Lock size={14} style={{ flexShrink: 0 }} />
                Original file confirmed preserved — SHA-256 unchanged.
              </div>
            )}
          </div>

          {/* Verify result */}
          <VerifyResult result={result.verify_result} />
        </div>
      )}
    </div>
  );
}
