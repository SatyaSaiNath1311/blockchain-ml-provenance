import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Cpu,
  Layers,
  Play,
  CheckCircle2,
  XCircle,
  RotateCcw,
  ShieldCheck,
  ShieldAlert,
  GitCommit,
  Check,
  ArrowRight,
  AlertCircle,
} from 'lucide-react';
import {
  listDatasets,
  getDatasetVersions,
  verifyGet,
  preprocessVersion,
  trainModel,
  getExperiment,
  getVersionExperiments,
  reproduceExperiment,
} from '../api/client';
import ErrorAlert from '../components/ErrorAlert';
import VerifyResult from '../components/VerifyResult';
import ShortId from '../components/ShortId';
import HashDisplay from '../components/HashDisplay';
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

export default function ExperimentsPage() {
  const [datasets, setDatasets] = useState(null);
  const [selectedDs, setSelectedDs] = useState('');
  const [versions, setVersions] = useState(null);
  const [selectedVer, setSelectedVer] = useState('');

  // Gate state
  const [gateLoading, setGateLoading] = useState(false);
  const [gateResult, setGateResult] = useState(null);
  const [gateError, setGateError] = useState('');

  // Preprocess state
  const [prepLoading, setPrepLoading] = useState(false);
  const [prepResult, setPrepResult] = useState(null);
  const [prepError, setPrepError] = useState('');

  // Train state
  const [trainLoading, setTrainLoading] = useState(false);
  const [trainResult, setTrainResult] = useState(null);
  const [trainError, setTrainError] = useState('');
  const [seed, setSeed] = useState(42);
  const [testSize, setTestSize] = useState(0.2);
  const [nEstimators, setNEstimators] = useState(100);

  // Past experiments state
  const [experiments, setExperiments] = useState([]);
  const [expLoading, setExpLoading] = useState(false);
  const [expError, setExpError] = useState('');
  const [reproducingRunId, setReproducingRunId] = useState(null);
  const [reproResults, setReproResults] = useState({});

  // Load datasets on mount
  useEffect(() => {
    let cancelled = false;
    listDatasets()
      .then((ds) => {
        if (!cancelled && ds) {
          setDatasets(ds);
          const sorted = [...ds].sort((a, b) => {
            const tA = a.created_at ? new Date(a.created_at).getTime() : 0;
            const tB = b.created_at ? new Date(b.created_at).getTime() : 0;
            return tB - tA;
          });
          const withVersions = sorted.find((d) => (d.version_count || 0) > 0) || sorted[0];
          if (withVersions) {
            setSelectedDs((curr) => curr || withVersions.dataset_id);
          }
        }
      })
      .catch((e) => {
        if (!cancelled) setGateError(`Failed to load datasets: ${e.message}`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // When dataset changes, fetch its versions
  useEffect(() => {
    if (!selectedDs) {
      return;
    }
    let cancelled = false;
    getDatasetVersions(selectedDs)
      .then((vList) => {
        if (!cancelled) {
          setVersions(vList);
          // Auto-select when a dataset has only one version or default to the first
          if (vList && vList.length > 0) {
            setSelectedVer(vList[0].version_id);
          } else {
            setSelectedVer('');
          }
        }
      })
      .catch((e) => {
        if (!cancelled) setGateError(`Failed to load versions: ${e.message}`);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDs]);

  const loadPastExperiments = useCallback((verId) => {
    if (!verId) {
      setExperiments([]);
      return;
    }
    Promise.resolve().then(() => {
      setExpLoading(true);
    });
    getVersionExperiments(verId)
      .then(async (runs) => {
        const list = Array.isArray(runs) ? runs : [];
        const detailed = await Promise.all(
          list.map(async (runItem) => {
            const runId = typeof runItem === 'string' ? runItem : (runItem?.run_id || runItem?.id);
            if (!runId) return runItem;
            try {
              const details = await getExperiment(runId);
              return { ...details, run_id: runId };
            } catch {
              return typeof runItem === 'object' ? runItem : { run_id: runId };
            }
          })
        );
        setExperiments(detailed);
        setExpError('');
      })
      .catch((e) => {
        setExpError(e.message);
      })
      .finally(() => {
        setExpLoading(false);
      });
  }, []);

  // When version changes, run verification gate & load past experiments
  useEffect(() => {
    if (!selectedVer) {
      return;
    }
    let cancelled = false;

    // Run async reset to prevent cascading render warnings
    Promise.resolve().then(() => {
      if (!cancelled) {
        setGateLoading(true);
        setGateError('');
        setGateResult(null);
        setPrepResult(null);
        setPrepError('');
        setTrainResult(null);
        setTrainError('');
        setReproResults({});
        loadPastExperiments(selectedVer);
      }
    });

    verifyGet(selectedVer)
      .then((res) => {
        if (!cancelled) setGateResult(res);
      })
      .catch((e) => {
        if (!cancelled) setGateError(e.message);
      })
      .finally(() => {
        if (!cancelled) setGateLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedVer, loadPastExperiments]);

  const handleDatasetChange = (e) => {
    const dsId = e.target.value;
    setSelectedDs(dsId);
    setVersions(null);
    setSelectedVer('');
    setGateResult(null);
  };

  const handleVersionChange = (e) => {
    setSelectedVer(e.target.value);
  };

  const isGatePassed = gateResult?.status === 'VERIFIED';

  // Handle Preprocess
  const handlePreprocess = async () => {
    if (!selectedVer) return;
    setPrepLoading(true);
    setPrepError('');
    setPrepResult(null);
    try {
      const res = await preprocessVersion(selectedVer);
      setPrepResult(res);
      // Refresh versions for the dataset so derived child appears
      if (selectedDs) {
        const vList = await getDatasetVersions(selectedDs);
        setVersions(vList);
      }
    } catch (e) {
      setPrepError(e.message);
    } finally {
      setPrepLoading(false);
    }
  };

  // Handle Train
  const handleTrain = async () => {
    if (!selectedVer || !isGatePassed) return;
    setTrainLoading(true);
    setTrainError('');
    setTrainResult(null);
    try {
      const config = {
        seed,
        test_size: testSize,
        n_estimators: nEstimators,
      };
      const res = await trainModel(selectedVer, config);
      setTrainResult(res);
      // Refresh past experiments
      loadPastExperiments(selectedVer);
    } catch (e) {
      setTrainError(e.message);
    } finally {
      setTrainLoading(false);
    }
  };

  // Handle Reproduce Run
  const handleReproduce = async (runId) => {
    if (!runId) return;
    setReproducingRunId(runId);
    try {
      const res = await reproduceExperiment(runId);
      setReproResults((prev) => ({ ...prev, [runId]: res }));
    } catch (e) {
      const errorMsg = e.response?.data?.detail || e.message;
      setReproResults((prev) => ({
        ...prev,
        [runId]: { status: 'ERROR', reason: errorMsg },
      }));
    } finally {
      setReproducingRunId(null);
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
        <h1 className="page-title">Machine learning experiments</h1>
        <p className="page-desc">
          Verification-gated data preprocessing, reproducible model training, and on-chain run registration.
        </p>
      </div>

      {/* Dataset & Version Selectors */}
      <div className="card mb-6">
        <div className="grid-2" style={{ gap: 'var(--sp-4)' }}>
          <div className="form-group">
            <label htmlFor="exp-dataset-select">Select dataset</label>
            <select
              id="exp-dataset-select"
              data-testid="dataset-select"
              value={selectedDs}
              onChange={handleDatasetChange}
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
          </div>

          <div className="form-group">
            <label htmlFor="exp-version-select">Select version</label>
            <select
              id="exp-version-select"
              data-testid="version-select"
              value={selectedVer}
              onChange={handleVersionChange}
              disabled={!versions || versions.length === 0}
            >
              <option value="">— choose version —</option>
              {versions?.map((v) => {
                const op = getOperationLabel(v);
                return (
                  <option key={v.version_id} value={v.version_id}>
                    {op} — {v.version_id.slice(0, 8)}… ({v.num_chunks ?? '—'} chunks)
                  </option>
                );
              })}
            </select>
          </div>
        </div>
      </div>

      {selectedVer && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-6)' }}>
          {/* Two-column layout above 1100px: Gate left, Actions right */}
          <div className="page-2col-experiments">
            {/* Left Column: Verification Gate Card */}
            <div
              className={`card ${isGatePassed ? 'card-pass' : gateError ? 'card-warn' : gateResult ? 'card-fail' : ''}`}
              data-testid="verification-gate-container"
            >
              <div className="card-header" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                  {isGatePassed ? (
                    <ShieldCheck size={22} style={{ color: 'var(--clr-pass)' }} />
                  ) : (
                    <ShieldAlert size={22} style={{ color: gateError ? 'var(--clr-warn)' : 'var(--clr-fail)' }} />
                  )}
                  <div>
                    <h2 className="card-title" style={{ margin: 0, fontSize: '1rem' }}>
                      Pre-training verification gate
                    </h2>
                    <p className="text-xs text-faint" style={{ margin: 0 }}>
                      Cryptographic integrity gate checked against Ethereum smart contract
                    </p>
                  </div>
                </div>

                {gateLoading ? (
                  <span className="badge badge-info">Checking gate…</span>
                ) : gateError ? (
                  <span className="badge badge-neutral" data-testid="gate-status-badge">
                    GATE: ERROR
                  </span>
                ) : isGatePassed ? (
                  <span className="badge badge-pass" data-testid="gate-status-badge">
                    GATE: PASS
                  </span>
                ) : gateResult ? (
                  <span className="badge badge-fail" data-testid="gate-status-badge">
                    GATE: FAIL
                  </span>
                ) : (
                  <span className="badge badge-neutral" data-testid="gate-status-badge">
                    GATE: UNCHECKED
                  </span>
                )}
              </div>

              <ErrorAlert message={gateError} />

              {gateLoading && <div className="text-xs text-faint">Verifying cryptographic digests against blockchain…</div>}

              {gateResult && (
                <div style={{ marginTop: 'var(--sp-2)' }}>
                  <VerifyResult result={gateResult} />
                </div>
              )}
            </div>

            {/* Right Column: Preprocess & Train Action Cards + Outputs */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
              {/* 1. Preprocess Card */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
                    <Layers size={18} style={{ color: 'var(--clr-accent)' }} />
                    <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                      Deterministic data cleaning
                    </h3>
                  </div>
                  <p className="text-xs text-faint mb-3">
                    Applies standardized normalization, drops identifiers, casts schema types, and registers a derived child version linked to parent on-chain.
                  </p>
                </div>

                <div>
                  <button
                    type="button"
                    className="btn btn-primary"
                    data-testid="preprocess-btn"
                    onClick={handlePreprocess}
                    disabled={prepLoading}
                    style={{ width: '100%', justifyContent: 'center' }}
                  >
                    <Layers size={15} />
                    {prepLoading ? 'Cleaning & Anchoring…' : 'Clean and anchor child version'}
                  </button>
                </div>
              </div>

              {/* Preprocess Error & Result */}
              <ErrorAlert message={prepError} />
              {prepResult && (
                <div className="card" data-testid="preprocess-result-container">
                  <div className="card-header" style={{ marginBottom: 'var(--sp-2)' }}>
                    <CheckCircle2 size={18} style={{ color: 'var(--clr-pass)' }} />
                    <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                      Derived dataset version anchored
                    </h3>
                  </div>
                  <p className="text-xs text-faint mb-3">
                    Preprocessed CSV written to storage and anchored on blockchain with parent linkage.
                  </p>

                  <div className="grid-2 mb-3" style={{ gap: 'var(--sp-2)' }}>
                    <div>
                      <span className="text-xs text-faint">Derived child version ID:</span>
                      <div className="mt-1" data-testid="derived-version-id">
                        <ShortId id={prepResult.version_id} length={12} />
                      </div>
                    </div>
                    <div>
                      <span className="text-xs text-faint">Parent version ID:</span>
                      <div className="mt-1">
                        <ShortId id={prepResult.parent_version_id} length={12} />
                      </div>
                    </div>
                  </div>

                  {prepResult.receipt?.tx_hash && (
                    <HashDisplay label="Transaction hash" value={prepResult.receipt.tx_hash} />
                  )}
                  <div style={{ marginTop: 'var(--sp-2)', display: 'flex', justifyContent: 'flex-end' }}>
                    <Link
                      to="/explorer"
                      data-testid="view-lineage-link"
                      className="btn btn-ghost btn-sm"
                    >
                      View lineage in Explorer <ArrowRight size={13} />
                    </Link>
                  </div>
                </div>
              )}

              {/* 2. Train Card */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
                    <Cpu size={18} style={{ color: 'var(--clr-accent)' }} />
                    <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                      Train baseline model
                    </h3>
                  </div>
                  <p className="text-xs text-faint mb-3">
                    Trains Random Forest classifier, evaluates metrics, and anchors run record and digest on-chain.
                  </p>

                  {/* Hyperparameters */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 'var(--sp-2)', marginBottom: 'var(--sp-3)' }}>
                    <div className="form-group">
                      <label htmlFor="train-seed" style={{ fontSize: 'var(--text-xs)' }}>Seed</label>
                      <input
                        id="train-seed"
                        type="number"
                        data-testid="train-seed-input"
                        value={seed}
                        onChange={(e) => setSeed(Number(e.target.value))}
                        style={{ padding: '4px var(--sp-2)', fontSize: 'var(--text-xs)' }}
                      />
                    </div>
                    <div className="form-group">
                      <label htmlFor="train-testsize" style={{ fontSize: 'var(--text-xs)' }}>Test size</label>
                      <input
                        id="train-testsize"
                        type="number"
                        step="0.05"
                        min="0.1"
                        max="0.5"
                        data-testid="train-testsize-input"
                        value={testSize}
                        onChange={(e) => setTestSize(Number(e.target.value))}
                        style={{ padding: '4px var(--sp-2)', fontSize: 'var(--text-xs)' }}
                      />
                    </div>
                    <div className="form-group">
                      <label htmlFor="train-estimators" style={{ fontSize: 'var(--text-xs)' }}>Estimators</label>
                      <input
                        id="train-estimators"
                        type="number"
                        min="10"
                        max="500"
                        data-testid="train-estimators-input"
                        value={nEstimators}
                        onChange={(e) => setNEstimators(Number(e.target.value))}
                        style={{ padding: '4px var(--sp-2)', fontSize: 'var(--text-xs)' }}
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <button
                    type="button"
                    className="btn btn-primary"
                    data-testid="train-btn"
                    onClick={handleTrain}
                    disabled={trainLoading || !isGatePassed}
                    style={{ width: '100%', justifyContent: 'center' }}
                  >
                    <Play size={15} />
                    {trainLoading ? 'Training model…' : 'Train model on verified version'}
                  </button>
                </div>
              </div>

              {/* Train Error & Result */}
              <ErrorAlert message={trainError} />
              {trainResult && (
                <div className="card" data-testid="train-result-container">
                  <div className="card-header" style={{ marginBottom: 'var(--sp-2)', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                      <CheckCircle2 size={18} style={{ color: 'var(--clr-pass)' }} />
                      <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                        Training run completed & anchored
                      </h3>
                    </div>
                    {trainResult.receipt?.block_number != null && (
                      <span className="badge badge-info">
                        Block #{trainResult.receipt.block_number}
                      </span>
                    )}
                  </div>

                  {/* Metrics Grid */}
                  <div
                    className="grid-4 mb-4"
                    data-testid="train-metrics"
                    style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 'var(--sp-2)', marginBottom: 'var(--sp-4)' }}
                  >
                    <MetricBox label="Accuracy" value={trainResult.metrics?.accuracy != null ? `${(trainResult.metrics.accuracy * 100).toFixed(1)}%` : '—'} />
                    <MetricBox label="F1 Score" value={trainResult.metrics?.f1 != null ? trainResult.metrics.f1.toFixed(3) : trainResult.metrics?.f1_score != null ? trainResult.metrics.f1_score.toFixed(3) : '—'} />
                    <MetricBox label="Precision" value={trainResult.metrics?.precision != null ? trainResult.metrics.precision.toFixed(3) : '—'} />
                    <MetricBox label="Recall" value={trainResult.metrics?.recall != null ? trainResult.metrics.recall.toFixed(3) : '—'} />
                    <MetricBox label="ROC AUC" value={trainResult.metrics?.roc_auc != null ? trainResult.metrics.roc_auc.toFixed(3) : '—'} />
                  </div>

                  {/* IDs */}
                  <div className="grid-2 mb-3" style={{ gap: 'var(--sp-2)' }}>
                    <div>
                      <span className="text-xs text-faint">Run ID:</span>
                      <div className="mt-1" data-testid="train-run-id">
                        <ShortId id={trainResult.run_id} length={12} />
                      </div>
                    </div>
                    <div>
                      <span className="text-xs text-faint">Trained on version ID:</span>
                      <div className="mt-1">
                        <ShortId id={trainResult.dataset_version_id} length={12} />
                      </div>
                    </div>
                  </div>

                  {/* Experiment Digest */}
                  <div className="mb-3" data-testid="train-digest">
                    <HashDisplay
                      label="Experiment digest (canonical SHA-256)"
                      value={trainResult.experiment_digest || trainResult.experiment_record?.experiment_digest || trainResult.on_chain?.experiment_digest}
                    />
                  </div>

                  {/* Tx Hash */}
                  {trainResult.receipt?.tx_hash && (
                    <div data-testid="train-receipt">
                      <HashDisplay label="On-chain transaction hash" value={trainResult.receipt.tx_hash} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Past Experiments & Reproducibility Section */}
          <div className="card" data-testid="experiments-list-container">
            <div className="card-header" style={{ marginBottom: 'var(--sp-3)' }}>
              <GitCommit size={18} style={{ color: 'var(--clr-accent)' }} />
              <div>
                <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                  Training runs on this version
                </h3>
                <p className="text-xs text-faint" style={{ margin: 0 }}>
                  On-chain anchored runs and bitwise reproducibility verification
                </p>
              </div>
            </div>

            <ErrorAlert message={expError} />

            {expLoading && <div className="text-xs text-faint">Loading past experiments…</div>}

            {!expLoading && experiments.length === 0 && (
              <EmptyState
                icon={Cpu}
                title="No training runs recorded"
                desc="Train a model on this verified dataset version to anchor reproducible metrics and lineage on-chain."
                actionLabel="Train model on verified version"
                onAction={handleTrain}
              />
            )}

            {!expLoading && experiments.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
                {experiments.map((exp, idx) => {
                  const runId = typeof exp === 'string' ? exp : (exp?.run_id || exp?.id);
                  const isReproducing = reproducingRunId === runId;
                  const repro = runId ? reproResults[runId] : null;

                  const metrics = exp?.experiment_record?.metrics || exp?.metrics;
                  const digest = exp?.on_chain?.experiment_digest || exp?.experiment_record?.experiment_digest || exp?.experiment_digest;
                  const receipt = exp?.receipt;

                  return (
                    <div
                      key={runId || idx}
                      data-testid={`experiment-item-${runId || idx}`}
                      style={{
                        background: 'var(--clr-surface-2)',
                        border: '1px solid var(--clr-border)',
                        borderRadius: 'var(--radius)',
                        padding: 'var(--sp-3)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--sp-2)' }}>
                        <div>
                          <span className="text-xs text-faint">Run ID:</span>
                          <div className="mt-1">
                            <ShortId id={runId} length={12} />
                          </div>
                        </div>

                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          data-testid={`reproduce-btn-${runId || 'disabled'}`}
                          onClick={() => handleReproduce(runId)}
                          disabled={isReproducing || !runId}
                        >
                          <RotateCcw size={13} />
                          {isReproducing ? 'Reproducing…' : 'Verify and reproduce experiment'}
                        </button>
                      </div>

                      {/* Run Metrics if loaded */}
                      {metrics && (
                        <div
                          className="mt-2 mb-2"
                          style={{
                            display: 'flex',
                            flexWrap: 'wrap',
                            gap: 'var(--sp-2)',
                            fontSize: 'var(--text-xs)',
                          }}
                        >
                          <span className="badge badge-neutral">
                            Acc: {metrics.accuracy != null ? `${(metrics.accuracy * 100).toFixed(1)}%` : '—'}
                          </span>
                          <span className="badge badge-neutral">
                            F1: {(metrics.f1 ?? metrics.f1_score) != null ? (metrics.f1 ?? metrics.f1_score).toFixed(3) : '—'}
                          </span>
                          <span className="badge badge-neutral">
                            Prec: {metrics.precision != null ? metrics.precision.toFixed(3) : '—'}
                          </span>
                          <span className="badge badge-neutral">
                            Rec: {metrics.recall != null ? metrics.recall.toFixed(3) : '—'}
                          </span>
                          <span className="badge badge-neutral">
                            ROC AUC: {metrics.roc_auc != null ? metrics.roc_auc.toFixed(3) : '—'}
                          </span>
                        </div>
                      )}

                      {/* Digest and receipt if available */}
                      {digest && (
                        <div className="mt-2" style={{ fontSize: 'var(--text-xs)' }}>
                          <HashDisplay label="Experiment digest" value={digest} />
                        </div>
                      )}
                      {receipt?.tx_hash && (
                        <div className="mt-2" style={{ fontSize: 'var(--text-xs)' }}>
                          <HashDisplay label="On-chain transaction hash" value={receipt.tx_hash} />
                        </div>
                      )}

                      {/* Reproducibility Result */}
                      {repro && (
                        <div
                          className="mt-3 pt-3"
                          data-testid={`reproduce-result-${runId}`}
                          style={{ borderTop: '1px solid var(--clr-border-faint)' }}
                        >
                          {repro.status === 'ERROR' ? (
                            <div
                              className="alert alert-error"
                              data-testid="reproduce-error-banner"
                              style={{ fontSize: 'var(--text-xs)', display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}
                            >
                              <AlertCircle size={16} style={{ flexShrink: 0, color: 'var(--clr-fail)' }} />
                              <div>
                                <strong>Reproduce request error: </strong>
                                {repro.reason || 'Verification request failed.'}
                              </div>
                            </div>
                          ) : (
                            <>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
                                <span className="text-xs text-faint">Result:</span>
                                {repro.status === 'REPRODUCED' ? (
                                  <span className="badge badge-pass" data-testid="reproduce-status-badge">
                                    REPRODUCED
                                  </span>
                                ) : (
                                  <span className="badge badge-fail" data-testid="reproduce-status-badge">
                                    {repro.status || 'MISMATCH'}
                                  </span>
                                )}
                                <span className="text-xs text-faint" style={{ marginLeft: 'auto' }}>
                                  {repro.reason}
                                </span>
                              </div>

                              {/* Verification matches */}
                              <div className="grid-3 mb-2" style={{ gap: 'var(--sp-2)', fontSize: 'var(--text-xs)' }}>
                                <div>
                                  Metrics match:{' '}
                                  {repro.metrics_match === true ? (
                                    <span style={{ color: 'var(--clr-pass)', fontWeight: 600 }}>PASS</span>
                                  ) : repro.metrics_match === false ? (
                                    <span style={{ color: 'var(--clr-fail)', fontWeight: 600 }}>FAIL</span>
                                  ) : (
                                    <span style={{ color: 'var(--clr-text-3)', fontWeight: 600 }}>—</span>
                                  )}
                                </div>
                                <div>
                                  Predictions match:{' '}
                                  {repro.predictions_match === true ? (
                                    <span style={{ color: 'var(--clr-pass)', fontWeight: 600 }}>PASS</span>
                                  ) : repro.predictions_match === false ? (
                                    <span style={{ color: 'var(--clr-fail)', fontWeight: 600 }}>FAIL</span>
                                  ) : (
                                    <span style={{ color: 'var(--clr-text-3)', fontWeight: 600 }}>—</span>
                                  )}
                                </div>
                                <div>
                                  Model intact:{' '}
                                  {repro.model_artifact_intact === true ? (
                                    <span style={{ color: 'var(--clr-pass)', fontWeight: 600 }}>PASS</span>
                                  ) : repro.model_artifact_intact === false ? (
                                    <span style={{ color: 'var(--clr-fail)', fontWeight: 600 }}>FAIL</span>
                                  ) : (
                                    <span style={{ color: 'var(--clr-text-3)', fontWeight: 600 }}>—</span>
                                  )}
                                </div>
                              </div>

                              {/* Comparison Table */}
                              {repro.original_metrics && repro.reproduced_metrics && (
                                <table style={{ width: '100%', fontSize: 'var(--text-sm)', marginTop: 'var(--sp-2)' }}>
                                  <thead>
                                    <tr>
                                      <th style={{ textAlign: 'left', padding: 'var(--sp-3) var(--sp-4)' }}>Metric</th>
                                      <th style={{ textAlign: 'right', padding: 'var(--sp-3) var(--sp-4)' }}>Original</th>
                                      <th style={{ textAlign: 'right', padding: 'var(--sp-3) var(--sp-4)' }}>Reproduced</th>
                                      <th style={{ textAlign: 'center', padding: 'var(--sp-3) var(--sp-4)' }}>Match</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {Object.keys(repro.original_metrics).map((m) => {
                                      const orig = repro.original_metrics[m];
                                      const rep = repro.reproduced_metrics[m];
                                      const match = orig === rep;
                                      return (
                                        <tr key={m}>
                                          <td style={{ padding: 'var(--sp-3) var(--sp-4)' }}>{m}</td>
                                          <td style={{ textAlign: 'right', padding: 'var(--sp-3) var(--sp-4)' }}>{orig}</td>
                                          <td style={{ textAlign: 'right', padding: 'var(--sp-3) var(--sp-4)' }}>{rep}</td>
                                          <td style={{ textAlign: 'center', padding: 'var(--sp-3) var(--sp-4)' }}>
                                            {match ? (
                                              <Check size={14} style={{ color: 'var(--clr-pass)' }} />
                                            ) : (
                                              <XCircle size={14} style={{ color: 'var(--clr-fail)' }} />
                                            )}
                                          </td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricBox({ label, value }) {
  return (
    <div
      style={{
        background: 'var(--clr-surface-2)',
        border: '1px solid var(--clr-border-faint)',
        borderRadius: 'var(--radius)',
        padding: 'var(--sp-2) var(--sp-3)',
        textAlign: 'center',
      }}
    >
      <div className="text-xs text-faint">{label}</div>
      <div style={{ fontSize: '1.05rem', fontWeight: 700, marginTop: 2, color: 'var(--clr-text)' }}>
        {value != null ? value : '—'}
      </div>
    </div>
  );
}
