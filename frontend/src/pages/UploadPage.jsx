import { useCallback, useRef, useState } from 'react';
import {
  UploadCloud,
  FileText,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileSpreadsheet,
  ArrowRight,
  ShieldCheck,
  FlaskConical,
  Cpu,
  Layers,
  Sparkles,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { uploadDataset } from '../api/client';
import ErrorAlert from '../components/ErrorAlert';
import HashDisplay from '../components/HashDisplay';
import ShortId from '../components/ShortId';

const SAMPLES = [
  {
    filename: 'customer_churn.csv',
    title: 'Customer churn',
    rows: '600 rows • 6 features',
    desc: 'Telecom subscriber churn dataset with ~82% Random Forest predictive accuracy.',
  },
  {
    filename: 'loan_approval.csv',
    title: 'Loan approval',
    rows: '600 rows • 8 columns',
    desc: 'Demographic and financial features designed for the cleaning and preprocessing pipeline.',
  },
  {
    filename: 'sensor_readings.csv',
    title: 'Sensor readings',
    rows: '500 rows • 7 telemetry signals',
    desc: 'Industrial IoT vibration, pressure, and voltage measurements with binary anomaly label.',
  },
];

const WALKTHROUGH_STEPS = [
  {
    num: 1,
    title: 'Upload and anchor a dataset',
    to: '/upload',
    badge: 'Step 1 (Here)',
    icon: UploadCloud,
    desc: 'Choose a CSV file or one of the sample datasets below, then click "Upload and anchor" to register its SHA-256 and chunked Merkle root on-chain.',
  },
  {
    num: 2,
    title: 'Verify stored file integrity',
    to: '/verify',
    badge: 'Step 2',
    icon: ShieldCheck,
    desc: 'Select the registered dataset version on the Verification page to cryptographically prove that the stored file matches on-chain roots.',
  },
  {
    num: 3,
    title: 'Simulate tampering on an isolated copy',
    to: '/lab',
    badge: 'Step 3',
    icon: FlaskConical,
    desc: 'Run controlled cell modification or label flipping attacks in the Tampering Lab on a temp copy without modifying the original dataset.',
  },
  {
    num: 4,
    title: 'Verify an externally modified file',
    to: '/verify',
    badge: 'Step 4',
    icon: Layers,
    desc: 'Use the "Upload file to compare" mode on the Verification page to upload a hand-edited copy and observe chunk-level localization.',
  },
  {
    num: 5,
    title: 'Run ML experiment & verify gate',
    to: '/experiments',
    badge: 'Step 5',
    icon: Cpu,
    desc: 'Clean the dataset into an immutable child version and train a Random Forest model, passing the pre-training verification gate.',
  },
];

export default function UploadPage() {
  const [file, setFile] = useState(null);
  const [chunkRows, setChunkRows] = useState(1000);
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingSample, setLoadingSample] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [showWalkthrough, setShowWalkthrough] = useState(true);
  const inputRef = useRef();

  const handleFile = (f) => {
    if (!f) return;
    setFile(f);
    setResult(null);
    setError('');
    setProgress(0);
  };

  const loadSample = async (sample) => {
    setError('');
    setLoadingSample(sample.filename);
    try {
      const resp = await fetch(`/samples/${sample.filename}`);
      if (!resp.ok) {
        throw new Error(`Failed to load ${sample.filename} (${resp.status})`);
      }
      const blob = await resp.blob();
      const loadedFile = new File([blob], sample.filename, { type: 'text/csv' });
      handleFile(loadedFile);
    } catch (e) {
      setError(`Could not load sample dataset: ${e.message}`);
    } finally {
      setLoadingSample('');
    }
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
    <div className="page-container">
      <div className="page-header">
        <h1 className="page-title">Upload dataset</h1>
        <p className="page-desc">
          Upload a CSV file — computes SHA-256 digest, builds Merkle tree, and anchors on-chain.
        </p>
      </div>

      <div className="page-2col-upload">
        {/* Left Column: Upload Form + Result Card */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-5)' }}>
          {/* Upload Form Card */}
          <div className="card">
            <div className="card-header">
              <UploadCloud size={18} style={{ color: 'var(--clr-accent)' }} />
              <div>
                <p className="card-title">Select or drop dataset</p>
                <p className="card-sub">Choose a local CSV file or load a deterministic sample dataset below</p>
              </div>
            </div>

            {/* Try a Sample Dataset Cards */}
            <div style={{ marginBottom: 'var(--sp-4)' }}>
              <span className="text-xs text-faint" style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.5px' }}>
                Try a sample dataset
              </span>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
                  gap: 'var(--sp-3)',
                  marginTop: 'var(--sp-2)',
                }}
              >
                {SAMPLES.map((sample) => (
                  <div
                    key={sample.filename}
                    style={{
                      padding: 'var(--sp-3)',
                      borderRadius: 'var(--radius)',
                      background: file?.name === sample.filename ? 'var(--clr-accent-dim)' : 'var(--clr-surface-2)',
                      border: file?.name === sample.filename ? '1px solid var(--clr-accent)' : '1px solid var(--clr-border-faint)',
                      cursor: 'pointer',
                      transition: 'all var(--tx)',
                    }}
                    onClick={() => loadSample(sample)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && loadSample(sample)}
                    aria-label={`Load sample dataset ${sample.title}`}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: '4px' }}>
                      <FileSpreadsheet size={15} style={{ color: 'var(--clr-accent)' }} />
                      <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--clr-text)' }}>
                        {sample.title}
                      </span>
                    </div>
                    <div className="text-xs text-faint mb-1">{sample.rows}</div>
                    <div className="text-xs text-muted" style={{ fontSize: 'var(--text-xs)', lineHeight: 1.35 }}>
                      {sample.desc}
                    </div>
                    <div style={{ marginTop: 'var(--sp-2)', textAlign: 'right' }}>
                      <span
                        style={{
                          fontSize: 'var(--text-xs)',
                          color: file?.name === sample.filename ? 'var(--clr-accent)' : 'var(--clr-text-3)',
                          fontWeight: 600,
                        }}
                      >
                        {loadingSample === sample.filename ? 'Loading…' : file?.name === sample.filename ? '✓ Selected' : 'Load sample →'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Dropzone */}
            <div
              className={`dropzone ${dragOver ? 'drag-over' : ''}`}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onClick={() => inputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
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
                  <span className="dropzone-text" style={{ color: 'var(--clr-text)', fontWeight: 600 }}>
                    {file.name}
                  </span>
                  <span className="dropzone-sub">
                    {(file.size / 1024).toFixed(1)} KB — click to change file
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

            {/* Chunk rows */}
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

            {/* Progress bar */}
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
              {loading ? 'Uploading…' : 'Upload and anchor'}
            </button>

            <ErrorAlert message={error} />
          </div>

          {/* Result Card */}
          {result && (
            <div className="card card-pass">
              <div className="card-header">
                <CheckCircle2 size={20} style={{ color: 'var(--clr-pass)' }} />
                <div>
                  <p className="card-title">Dataset anchored on-chain</p>
                  <p className="card-sub">Root version registered with deterministic Merkle verification</p>
                </div>
              </div>

              <div className="grid-2" style={{ gap: 'var(--sp-3)' }}>
                <div>
                  <span className="text-xs text-faint">Dataset ID</span>
                  <div>
                    <ShortId id={result.metadata.dataset_id} length={12} />
                  </div>
                </div>
                <div>
                  <span className="text-xs text-faint">Version ID</span>
                  <div>
                    <ShortId id={result.metadata.version_id} length={12} />
                  </div>
                </div>
                <div>
                  <span className="text-xs text-faint">Chunks</span>
                  <div className="text-sm" style={{ fontWeight: 600 }}>{result.metadata.num_chunks}</div>
                </div>
                <div>
                  <span className="text-xs text-faint">Chunk rows</span>
                  <div className="text-sm" style={{ fontWeight: 600 }}>{result.metadata.chunk_rows}</div>
                </div>
              </div>

              <hr className="divider" />
              <HashDisplay label="SHA-256 file hash" value={result.metadata.file_hash} />
              <div className="mt-3">
                <HashDisplay label="Merkle root" value={result.metadata.merkle_root} />
              </div>
              {result.receipt?.tx_hash && (
                <div className="mt-3">
                  <HashDisplay label="Transaction hash" value={result.receipt.tx_hash} />
                </div>
              )}
              {result.receipt?.block_number != null && (
                <div className="mt-3">
                  <HashDisplay label="Block number" value={String(result.receipt.block_number)} />
                </div>
              )}
              {result.receipt?.gas_used != null && (
                <div className="mt-3">
                  <HashDisplay label="Gas used" value={Number(result.receipt.gas_used).toLocaleString()} />
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: Guided Demo Walkthrough (Sticky) */}
        <div className="sticky-col">
          <div className="card" style={{ padding: 'var(--sp-4)' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                cursor: 'pointer',
                userSelect: 'none',
              }}
              onClick={() => setShowWalkthrough((v) => !v)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setShowWalkthrough((v) => !v)}
              aria-expanded={showWalkthrough}
              aria-label="Toggle demo walkthrough guide"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                <Sparkles size={18} style={{ color: 'var(--clr-accent)' }} />
                <span className="card-title" style={{ fontSize: 'var(--text-base)' }}>Demo walkthrough</span>
                <span className="badge badge-info" style={{ fontSize: 'var(--text-xs)' }}>5 steps</span>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                aria-label={showWalkthrough ? 'Collapse demo walkthrough' : 'Expand demo walkthrough'}
                style={{ padding: '2px 6px', border: 'none' }}
              >
                {showWalkthrough ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>
            </div>

            {showWalkthrough && (
              <div style={{ marginTop: 'var(--sp-4)', display: 'flex', flexDirection: 'column' }}>
                {WALKTHROUGH_STEPS.map((step) => {
                  const Icon = step.icon;
                  return (
                    <div key={step.num} className="walkthrough-step-row">
                      <div
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: '50%',
                          background: 'var(--clr-accent-dim)',
                          color: 'var(--clr-accent)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 'var(--text-xs)',
                          fontWeight: 700,
                          flexShrink: 0,
                          marginTop: 2,
                        }}
                      >
                        {step.num}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
                          <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--clr-text)' }}>
                            {step.title}
                          </span>
                          <span className="badge badge-neutral" style={{ fontSize: 'var(--text-xs)' }}>
                            {step.badge}
                          </span>
                        </div>
                        <p className="text-xs text-muted" style={{ marginTop: '2px', lineHeight: 1.35 }}>
                          {step.desc}
                        </p>
                      </div>
                      {step.to !== '/upload' && (
                        <Link
                          to={step.to}
                          className="btn btn-ghost btn-sm"
                          style={{ alignSelf: 'center', fontSize: 'var(--text-xs)', flexShrink: 0, padding: '4px var(--sp-3)' }}
                        >
                          <Icon size={12} />
                          Go
                          <ArrowRight size={12} />
                        </Link>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
