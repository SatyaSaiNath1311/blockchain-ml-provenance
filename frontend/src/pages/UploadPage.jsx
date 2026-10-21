import { useCallback, useRef, useState } from 'react';
import { UploadCloud, FileText, CheckCircle2, Copy, Check } from 'lucide-react';
import { uploadDataset } from '../api/client';
import ErrorAlert from '../components/ErrorAlert';
import HashDisplay from '../components/HashDisplay';

export default function UploadPage() {
  const [file, setFile] = useState(null);
  const [chunkRows, setChunkRows] = useState(1000);
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState(0);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [copiedTx, setCopiedTx] = useState(false);
  const inputRef = useRef();

  const handleFile = (f) => {
    if (!f) return;
    setFile(f);
    setResult(null);
    setError('');
    setProgress(0);
    setCopiedTx(false);
  };

  const copyTxHash = (hash) => {
    if (!hash) return;
    navigator.clipboard?.writeText(hash).then(() => {
      setCopiedTx(true);
      setTimeout(() => setCopiedTx(false), 2000);
    }).catch(() => {});
  };

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, []);

  const onDragOver = (e) => { e.preventDefault(); setDragOver(true); };
  const onDragLeave = () => setDragOver(false);

  const submit = async () => {
    if (!file) return;
    setLoading(true);
    setError('');
    setResult(null);
    setProgress(0);
    setCopiedTx(false);
    try {
      const res = await uploadDataset(file, chunkRows, setProgress);
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
        <h1 className="page-title">Upload Dataset</h1>
        <p className="page-desc">
          Ingest a CSV file — computes SHA-256, builds Merkle tree, and anchors on-chain.
        </p>
      </div>

      <div className="card" style={{ maxWidth: 640 }}>
        {/* Dropzone */}
        <div
          className={`dropzone ${dragOver ? 'drag-over' : ''}`}
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
          aria-label="Drop CSV file here or click to browse"
        >
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            style={{ display: 'none' }}
            onChange={(e) => handleFile(e.target.files[0])}
          />
          {file ? (
            <>
              <FileText size={32} style={{ color: 'var(--clr-accent)' }} />
              <span className="dropzone-text" style={{ color: 'var(--clr-text)' }}>
                {file.name}
              </span>
              <span className="dropzone-sub">
                {(file.size / 1024).toFixed(1)} KB — click to change
              </span>
            </>
          ) : (
            <>
              <UploadCloud size={32} className="dropzone-icon" />
              <span className="dropzone-text">Drop CSV here or click to browse</span>
              <span className="dropzone-sub">Only .csv files accepted, max 50 MB</span>
            </>
          )}
        </div>

        {/* chunk_rows */}
        <div className="form-group mt-4">
          <label htmlFor="chunk-rows">Rows per chunk</label>
          <input
            id="chunk-rows"
            type="number"
            min={1}
            value={chunkRows}
            onChange={(e) => setChunkRows(Number(e.target.value))}
            style={{ maxWidth: 140 }}
          />
        </div>

        {/* Progress */}
        {loading && (
          <div className="mt-3">
            <div className="progress-bar">
              <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
            </div>
            <p className="text-xs text-faint mt-2">{progress}% uploaded…</p>
          </div>
        )}

        <button
          type="button"
          className="btn btn-primary btn-lg mt-4"
          disabled={!file || loading}
          onClick={submit}
          id="upload-btn"
        >
          <UploadCloud size={16} />
          {loading ? 'Uploading…' : 'Upload & Anchor'}
        </button>

        <ErrorAlert message={error} />
      </div>

      {/* Result card */}
      {result && (
        <div className="card mt-6" style={{ maxWidth: 720 }}>
          <div className="card-header">
            <CheckCircle2 size={20} style={{ color: 'var(--clr-pass)' }} />
            <div>
              <p className="card-title">Dataset anchored on-chain</p>
            </div>
          </div>

          <div className="grid-2" style={{ gap: 'var(--sp-3)' }}>
            <InfoRow label="Dataset ID" value={result.metadata.dataset_id} mono />
            <InfoRow label="Version ID" value={result.metadata.version_id} mono />
            <InfoRow label="Chunks" value={result.metadata.num_chunks} />
            <InfoRow label="Chunk rows" value={result.metadata.chunk_rows} />
          </div>

          <hr className="divider" />
          <HashDisplay label="SHA-256 file hash" value={result.metadata.file_hash} />
          <div className="mt-3">
            <HashDisplay label="Merkle root" value={result.metadata.merkle_root} />
          </div>
          {result.receipt?.tx_hash && (
            <div className="mt-3">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <span className="text-xs text-faint">Transaction hash</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                  <span className="hash" style={{ flex: 1 }}>{result.receipt.tx_hash}</span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => copyTxHash(result.receipt.tx_hash)}
                    title="Copy transaction hash"
                    aria-label="Copy transaction hash"
                    id="copy-tx-hash-btn"
                    style={{ padding: '3px 8px', fontSize: '.72rem', flexShrink: 0 }}
                  >
                    {copiedTx ? <Check size={12} style={{ color: 'var(--clr-pass)' }} /> : <Copy size={12} />}
                    {copiedTx ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </div>
            </div>
          )}
          {result.receipt?.block_number != null && (
            <div className="mt-3">
              <HashDisplay label="Block number" value={String(result.receipt.block_number)} />
            </div>
          )}
          {result.receipt?.gas_used != null && (
            <div className="mt-3">
              <HashDisplay label="Gas used" value={String(result.receipt.gas_used)} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value, mono = false }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="text-xs text-faint">{label}</span>
      <span className={mono ? 'hash' : 'text-sm'} style={mono ? {} : { fontWeight: 500 }}>
        {value ?? '—'}
      </span>
    </div>
  );
}
