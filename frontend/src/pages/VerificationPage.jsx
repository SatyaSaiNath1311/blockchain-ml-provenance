import { useEffect, useRef, useState } from 'react';
import { ShieldCheck, Upload, Search } from 'lucide-react';
import { listDatasets, getDatasetVersions, verifyGet, verifyPost } from '../api/client';
import VerifyResult from '../components/VerifyResult';
import ErrorAlert from '../components/ErrorAlert';
import { SkeletonRows } from '../components/Skeleton';
import EmptyState from '../components/EmptyState';

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

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Verification</h1>
        <p className="page-desc">
          Verify cryptographic integrity of any dataset version against the on-chain record.
        </p>
      </div>

      <div className="card" style={{ maxWidth: 640 }}>
        <div className="card-header">
          <ShieldCheck size={18} style={{ color: 'var(--clr-accent)' }} />
          <p className="card-title">Select version</p>
        </div>

        {/* Dataset picker */}
        <div className="form-group mb-4">
          <label htmlFor="ds-select">Dataset</label>
          <ErrorAlert message={dsError} />
          {!datasets && !dsError && <SkeletonRows n={1} />}
          {datasets && (
            <select id="ds-select" value={selectedDs} onChange={(e) => setSelectedDs(e.target.value)}>
              <option value="">— choose dataset —</option>
              {datasets.map((d) => (
                <option key={d.dataset_id} value={d.dataset_id}>
                  {d.filename} ({d.dataset_id.slice(0, 8)}…)
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Version picker */}
        {selectedDs && (
          <div className="form-group mb-4">
            <label htmlFor="ver-select">Version</label>
            <ErrorAlert message={verError} />
            {!versions && !verError && <SkeletonRows n={1} />}
            {versions && (
              <select id="ver-select" value={selectedVer} onChange={(e) => { setSelectedVer(e.target.value); setResult(null); }}>
                <option value="">— choose version —</option>
                {versions.map((v) => (
                  <option key={v.version_id} value={v.version_id}>
                    {v.operation_type ?? 'ingest'} — {v.version_id.slice(0, 8)}…
                  </option>
                ))}
              </select>
            )}
            {versions?.length === 0 && <EmptyState title="No versions" />}
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
                Verify stored file
              </button>
              <button
                type="button"
                id="mode-upload"
                className={`btn ${mode === 'upload' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setMode('upload')}
              >
                <Upload size={14} />
                Upload file to verify
              </button>
            </div>

            {mode === 'upload' && (
              <div className="form-group mb-4">
                <label htmlFor="verify-file">CSV file to verify</label>
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

      {result && (
        <div className="mt-6" style={{ maxWidth: 760 }}>
          <VerifyResult result={result} />
        </div>
      )}
    </div>
  );
}
