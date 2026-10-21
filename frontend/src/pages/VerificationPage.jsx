import { useEffect, useRef, useState } from 'react';
import { ShieldCheck, Upload, Search } from 'lucide-react';
import { listDatasets, getDatasetVersions, verifyGet, verifyPost } from '../api/client';
import VerifyResult from '../components/VerifyResult';
import ErrorAlert from '../components/ErrorAlert';
import { SkeletonRows } from '../components/Skeleton';
import EmptyState from '../components/EmptyState';

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

export default function VerificationPage() {
  const [datasets, setDatasets] = useState(null);
  const [dsError, setDsError] = useState('');
  const [selectedDs, setSelectedDs] = useState('');
  const [versions, setVersions] = useState(null);
  const [verError, setVerError] = useState('');
  const [selectedVer, setSelectedVer] = useState('');

  const [mode, setMode] = useState('stored'); // stored | upload
  const [uploadFile, setUploadFile] = useState(null);
  const fileRef = useRef();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

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

  const verify = async () => {
    if (!selectedVer) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res =
        mode === 'stored'
          ? await verifyGet(selectedVer)
          : await verifyPost(selectedVer, uploadFile);
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
        <h1 className="page-title">Dataset verification</h1>
        <p className="page-desc">
          Verify cryptographic integrity and provenance lineage of any dataset version against the on-chain record.
        </p>
      </div>

      <div className="page-2col-split">
        {/* Left Column: Controls */}
        <div className="card">
          <div className="card-header">
            <ShieldCheck size={18} style={{ color: 'var(--clr-accent)' }} />
            <div>
              <p className="card-title">Select version to verify</p>
              <p className="card-sub">Choose a dataset and target version recorded on-chain</p>
            </div>
          </div>

          {/* Dataset picker */}
          <div className="form-group mb-4">
            <label htmlFor="ds-select">Dataset</label>
            <ErrorAlert message={dsError} />
            {!datasets && !dsError && <SkeletonRows n={1} />}
            {datasets && (
              <select
                id="ds-select"
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
                desc="Upload and anchor your first CSV dataset before verifying."
                actionLabel="Upload and anchor dataset"
                actionHref="/"
              />
            )}
          </div>

          {/* Version picker */}
          {selectedDs && (
            <div className="form-group mb-4">
              <label htmlFor="ver-select">Version</label>
              <ErrorAlert message={verError} />
              {!versions && !verError && <SkeletonRows n={1} />}
              {versions && (
                <select
                  id="ver-select"
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

          {/* Mode toggle */}
          {selectedVer && (
            <>
              <div className="flex gap-2 mb-4">
                <button
                  type="button"
                  id="mode-stored"
                  className={`btn ${mode === 'stored' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setMode('stored')}
                >
                  <ShieldCheck size={14} />
                  Stored file
                </button>
                <button
                  type="button"
                  id="mode-upload"
                  className={`btn ${mode === 'upload' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setMode('upload')}
                >
                  <Upload size={14} />
                  Uploaded file
                </button>
              </div>

              {mode === 'upload' && (
                <div className="form-group mb-4">
                  <label htmlFor="verify-file">Local CSV file to compare</label>
                  <input
                    id="verify-file"
                    ref={fileRef}
                    type="file"
                    accept=".csv"
                    onChange={(e) => setUploadFile(e.target.files[0])}
                  />
                </div>
              )}

              <button
                type="button"
                id="verify-btn"
                className="btn btn-primary btn-lg"
                disabled={loading || (mode === 'upload' && !uploadFile)}
                onClick={verify}
              >
                <Search size={16} />
                {loading ? 'Verifying…' : 'Run verification'}
              </button>
            </>
          )}

          <ErrorAlert message={error} />
        </div>

        {/* Right Column: Verification Results */}
        <div>
          {result ? (
            <VerifyResult result={result} />
          ) : (
            <div className="card" style={{ borderStyle: 'dashed', textAlign: 'center', padding: 'var(--sp-8) var(--sp-6)' }}>
              <ShieldCheck size={36} style={{ color: 'var(--clr-text-3)', margin: '0 auto var(--sp-3)' }} />
              <p className="card-title" style={{ fontSize: '1rem', color: 'var(--clr-text-2)' }}>No verification run yet</p>
              <p className="text-xs text-muted" style={{ maxWidth: 360, margin: 'var(--sp-2) auto 0' }}>
                Select a dataset and version on the left, then click verify to check SHA-256 and Merkle proofs against the blockchain.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
