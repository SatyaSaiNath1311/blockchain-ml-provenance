import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Cpu,
  Play,
  RotateCcw,
  CheckCircle2,
  XCircle,
  Copy,
  Check,
  Layers,
  ArrowRight,
  ShieldCheck,
  ShieldAlert,
  Sliders,
} from 'lucide-react';
import {
  listDatasets,
  getDatasetVersions,
  verifyGet,
  preprocessVersion,
  trainVersion,
  getVersionExperiments,
  reproduceExperiment,
} from '../api/client';
import ErrorAlert from '../components/ErrorAlert';
import VerifyResult from '../components/VerifyResult';
import { SkeletonCard } from '../components/Skeleton';

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
  const [copiedDigest, setCopiedDigest] = useState(false);
  const [copiedTx, setCopiedTx] = useState(false);

  // Load datasets on mount
  useEffect(() => {
    let cancelled = false;
    listDatasets()
      .then((ds) => {
        if (!cancelled) setDatasets(ds);
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
    setExpLoading(true);
    setExpError('');
    getVersionExperiments(verId)
      .then((runs) => {
        setExperiments(runs || []);
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
    setGateLoading(true);
    setGateError('');
    setGateResult(null);
    setPrepResult(null);
    setPrepError('');
    setTrainResult(null);
    setTrainError('');
    setReproResults({});

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

    loadPastExperiments(selectedVer);

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
      const cfg = {
        seed: Number(seed),
        test_size: Number(testSize),
        n_estimators: Number(nEstimators),
      };
      const res = await trainVersion(selectedVer, cfg);
      setTrainResult(res);
      // Refresh past experiments
      loadPastExperiments(selectedVer);
    } catch (e) {
      setTrainError(e.message);
    } finally {
      setTrainLoading(false);
    }
  };

  // Handle Reproduce
  const handleReproduce = async (runId) => {
    setReproducingRunId(runId);
    try {
      const res = await reproduceExperiment(runId);
      setReproResults((prev) => ({ ...prev, [runId]: res }));
    } catch (e) {
      setReproResults((prev) => ({
        ...prev,
        [runId]: { status: 'ERROR', reason: e.message },
      }));
    } finally {
      setReproducingRunId(null);
    }
  };

  const copyDigest = (text) => {
    if (!text) return;
    navigator.clipboard?.writeText(text).then(() => {
      setCopiedDigest(true);
      setTimeout(() => setCopiedDigest(false), 2000);
    });
  };

  const copyTx = (text) => {
    if (!text) return;
    navigator.clipboard?.writeText(text).then(() => {
      setCopiedTx(true);
      setTimeout(() => setCopiedTx(false), 2000);
    });
  };

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">ML Experiments & Gate Pipeline</h1>
        <p className="page-desc">
          Verification-gated data preprocessing, reproducible model training, and on-chain run registration.
        </p>
      </div>

      {/* Dataset & Version Selectors */}
      <div className="card mb-6" style={{ maxWidth: 840 }}>
        <div className="grid-2" style={{ gap: 'var(--sp-4)' }}>
          <div className="form-group">
            <label htmlFor="exp-dataset-select">Select Dataset</label>
            <select
              id="exp-dataset-select"
              data-testid="dataset-select"
              value={selectedDs}
              onChange={handleDatasetChange}
            >
              <option value="">— Choose a dataset —</option>
              {datasets?.map((d) => (
                <option key={d.dataset_id} value={d.dataset_id}>
                  {d.filename} ({d.dataset_id.slice(0, 8)}…) — {d.version_count} v
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="exp-version-select">Select Version</label>
            <select
              id="exp-version-select"
              data-testid="version-select"
              value={selectedVer}
              onChange={handleVersionChange}
              disabled={!versions || versions.length === 0}
            >
              <option value="">— Choose a version —</option>
              {versions?.map((v) => (
                <option key={v.version_id} value={v.version_id}>
                  v{v.version_id.slice(0, 8)}… ({v.operation_type || 'ingest'})
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {selectedVer && (
        <div style={{ maxWidth: 840, display: 'flex', flexDirection: 'column', gap: 'var(--sp-5)' }}>
          {/* Verification Gate Card */}
          <div className="card" data-testid="verification-gate-container">
            <div className="card-header" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                {isGatePassed ? (
                  <ShieldCheck size={22} style={{ color: 'var(--clr-pass)' }} />
                ) : (
                  <ShieldAlert size={22} style={{ color: 'var(--clr-fail)' }} />
                )}
                <div>
                  <h2 className="card-title" style={{ margin: 0, fontSize: '1rem' }}>
                    Pre-Training Verification Gate
                  </h2>
                  <p className="text-xs text-faint" style={{ margin: 0 }}>
                    Cryptographic integrity gate checked against Ethereum smart contract
                  </p>
                </div>
              </div>

              {gateLoading ? (
                <span className="badge badge-info">Checking gate…</span>
              ) : isGatePassed ? (
                <span className="badge badge-pass" data-testid="gate-status-badge">
                  GATE: PASS
                </span>
              ) : (
                <span className="badge badge-fail" data-testid="gate-status-badge">
                  GATE: BLOCKED
                </span>
              )}
            </div>

            {gateLoading && <SkeletonCard />}
            <ErrorAlert message={gateError} />

            {gateResult && (
              <div className="mt-3">
                <VerifyResult result={gateResult} />
                {!isGatePassed && (
                  <div
                    style={{
                      background: 'var(--clr-fail-bg)',
                      border: '1px solid var(--clr-fail)',
                      borderRadius: 'var(--radius)',
                      padding: 'var(--sp-3)',
                      marginTop: 'var(--sp-3)',
                      color: 'var(--clr-fail)',
                      fontSize: '.82rem',
                    }}
                  >
                    <strong>Integrity Gate Warning:</strong> This version failed cryptographic verification.
                    Model training is strictly blocked to prevent contaminated training runs.
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Action Row: Preprocess & Train */}
          <div className="grid-2" style={{ gap: 'var(--sp-4)' }}>
            {/* 1. Preprocess Card */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
                  <Layers size={18} style={{ color: 'var(--clr-accent)' }} />
                  <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                    Deterministic Preprocessing
                  </h3>
                </div>
                <p className="text-xs text-faint mb-3">
                  Cleans dataset (normalizes categoricals, handles missing values) and anchors a derived child version on-chain.
                </p>
              </div>

              <div>
                <button
                  type="button"
                  className="btn btn-primary"
                  data-testid="preprocess-btn"
                  onClick={handlePreprocess}
                  disabled={prepLoading || !isGatePassed}
                  style={{ width: '100%', justifyContent: 'center' }}
                >
                  <Layers size={15} />
                  {prepLoading ? 'Cleaning & Anchoring…' : 'Preprocess Dataset'}
                </button>
              </div>
            </div>

            {/* 2. Train Card */}
            <div className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
                  <Cpu size={18} style={{ color: 'var(--clr-accent)' }} />
                  <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                    Train Baseline Model
                  </h3>
                </div>
                <p className="text-xs text-faint mb-3">
                  Trains Random Forest classifier, evaluates metrics, and anchors run record and digest on-chain.
                </p>

                {/* Hyperparameters */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 'var(--sp-2)', marginBottom: 'var(--sp-3)' }}>
                  <div className="form-group">
                    <label htmlFor="train-seed" style={{ fontSize: '.7rem' }}>Seed</label>
                    <input
                      id="train-seed"
                      type="number"
                      data-testid="train-seed-input"
                      value={seed}
                      onChange={(e) => setSeed(Number(e.target.value))}
                      style={{ padding: '2px 6px', fontSize: '.78rem' }}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="train-testsize" style={{ fontSize: '.7rem' }}>Test Size</label>
                    <input
                      id="train-testsize"
                      type="number"
                      step="0.05"
                      min="0.1"
                      max="0.5"
                      data-testid="train-testsize-input"
                      value={testSize}
                      onChange={(e) => setTestSize(Number(e.target.value))}
                      style={{ padding: '2px 6px', fontSize: '.78rem' }}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="train-estimators" style={{ fontSize: '.7rem' }}>Estimators</label>
                    <input
                      id="train-estimators"
                      type="number"
                      min="10"
                      max="500"
                      data-testid="train-estimators-input"
                      value={nEstimators}
                      onChange={(e) => setNEstimators(Number(e.target.value))}
                      style={{ padding: '2px 6px', fontSize: '.78rem' }}
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
                  {trainLoading ? 'Training Model…' : 'Train Model'}
                </button>
              </div>
            </div>
          </div>

          {/* Preprocess Error & Result */}
          <ErrorAlert message={prepError} />
          {prepResult && (
            <div className="card" data-testid="preprocess-result-container">
              <div className="card-header" style={{ marginBottom: 'var(--sp-2)' }}>
                <CheckCircle2 size={18} style={{ color: 'var(--clr-pass)' }} />
                <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                  Derived Dataset Version Anchored
                </h3>
              </div>
              <p className="text-xs text-faint mb-3">
                Preprocessed CSV written to storage and anchored on blockchain with parent linkage.
              </p>

              <div className="grid-2 mb-3" style={{ gap: 'var(--sp-2)' }}>
                <div>
                  <span className="text-xs text-faint">Derived Child Version ID:</span>
                  <div className="hash mt-1" data-testid="derived-version-id">
                    {prepResult.version_id}
                  </div>
                </div>
                <div>
                  <span className="text-xs text-faint">Parent Version ID:</span>
                  <div className="hash mt-1">{prepResult.parent_version_id}</div>
                </div>
              </div>

              <div style={{ display: 'flex', gap: 'var(--sp-4)', alignItems: 'center' }}>
                <span className="text-xs text-faint">
                  Rows: {prepResult.metadata?.provenance?.operation_params?.rows_before} → {prepResult.metadata?.provenance?.operation_params?.rows_after}
                </span>
                <Link
                  to="/explorer"
                  data-testid="view-lineage-link"
                  className="btn btn-ghost btn-sm"
                  style={{ marginLeft: 'auto' }}
                >
                  View Lineage in Explorer <ArrowRight size={13} />
                </Link>
              </div>
            </div>
          )}

          {/* Train Error & Result */}
          <ErrorAlert message={trainError} />
          {trainResult && (
            <div className="card" data-testid="train-result-container">
              <div className="card-header" style={{ marginBottom: 'var(--sp-2)' }}>
                <CheckCircle2 size={18} style={{ color: 'var(--clr-pass)' }} />
                <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                  Model Training Completed & Anchored
                </h3>
              </div>

              {/* Run ID & Metrics */}
              <div className="mb-3">
                <span className="text-xs text-faint">Run ID:</span>
                <div className="hash mt-1" data-testid="train-run-id">
                  {trainResult.run_id}
                </div>
              </div>

              <div className="grid-4 mb-4" data-testid="train-metrics" style={{ gap: 'var(--sp-2)' }}>
                <MetricBox label="Accuracy" value={trainResult.metrics?.accuracy} />
                <MetricBox label="Precision" value={trainResult.metrics?.precision} />
                <MetricBox label="Recall" value={trainResult.metrics?.recall} />
                <MetricBox label="F1 Score" value={trainResult.metrics?.f1} />
              </div>

              {/* Experiment Digest */}
              <div className="mb-3" data-testid="train-digest">
                <span className="text-xs text-faint">Experiment Digest (Canonical Metadata Hash):</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginTop: 4 }}>
                  <span className="hash" style={{ flex: 1 }}>
                    {trainResult.experiment_record?.experiment_digest}
                  </span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => copyDigest(trainResult.experiment_record?.experiment_digest)}
                    style={{ padding: '3px 8px', fontSize: '.72rem' }}
                  >
                    {copiedDigest ? <Check size={12} style={{ color: 'var(--clr-pass)' }} /> : <Copy size={12} />}
                    {copiedDigest ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </div>

              {/* On-chain Receipt */}
              {trainResult.receipt && (
                <div data-testid="train-receipt" style={{ background: 'var(--clr-surface-2)', padding: 'var(--sp-3)', borderRadius: 'var(--radius)' }}>
                  <span className="text-xs text-faint" style={{ fontWeight: 600 }}>On-Chain Transaction Receipt:</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginTop: 4 }}>
                    <span className="text-xs text-faint">Tx Hash:</span>
                    <span className="hash" style={{ flex: 1 }}>
                      {trainResult.receipt.tx_hash}
                    </span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => copyTx(trainResult.receipt.tx_hash)}
                      style={{ padding: '3px 8px', fontSize: '.72rem' }}
                    >
                      {copiedTx ? <Check size={12} style={{ color: 'var(--clr-pass)' }} /> : <Copy size={12} />}
                    </button>
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--sp-4)', marginTop: 4 }}>
                    <span className="text-xs text-faint">Block: <strong>{trainResult.receipt.block_number}</strong></span>
                    <span className="text-xs text-faint">Gas Used: <strong>{trainResult.receipt.gas_used?.toLocaleString()}</strong></span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Past Experiments List */}
          <div className="card" data-testid="experiments-list-container">
            <div className="card-header" style={{ marginBottom: 'var(--sp-3)' }}>
              <Sliders size={18} style={{ color: 'var(--clr-accent)' }} />
              <div>
                <h3 className="card-title" style={{ fontSize: '.95rem', margin: 0 }}>
                  Recorded Experiments for Version
                </h3>
                <span className="text-xs text-faint">
                  {experiments.length} run{experiments.length !== 1 ? 's' : ''} retrieved from blockchain events
                </span>
              </div>
            </div>

            <ErrorAlert message={expError} />
            {expLoading && <SkeletonCard />}

            {!expLoading && experiments.length === 0 && (
              <p className="text-xs text-faint" style={{ fontStyle: 'italic', margin: 0 }}>
                No training runs recorded for this dataset version yet.
              </p>
            )}

            {!expLoading && experiments.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
                {experiments.map((runId) => {
                  const repro = reproResults[runId];
                  const isReproducing = reproducingRunId === runId;

                  return (
                    <div
                      key={runId}
                      data-testid={`experiment-item-${runId}`}
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
                          <div className="hash" style={{ fontWeight: 600 }}>{runId}</div>
                        </div>

                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          data-testid={`reproduce-btn-${runId}`}
                          onClick={() => handleReproduce(runId)}
                          disabled={isReproducing}
                        >
                          <RotateCcw size={13} />
                          {isReproducing ? 'Reproducing…' : 'Reproduce Run'}
                        </button>
                      </div>

                      {/* Reproducibility Result */}
                      {repro && (
                        <div
                          className="mt-3 pt-3"
                          data-testid={`reproduce-result-${runId}`}
                          style={{ borderTop: '1px solid var(--clr-border-faint)' }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
                            <span className="text-xs text-faint">Result:</span>
                            {repro.status === 'REPRODUCED' ? (
                              <span className="badge badge-pass" data-testid="reproduce-status-badge">
                                REPRODUCED
                              </span>
                            ) : (
                              <span className="badge badge-fail" data-testid="reproduce-status-badge">
                                {repro.status}
                              </span>
                            )}
                            <span className="text-xs text-faint" style={{ marginLeft: 'auto' }}>
                              {repro.reason}
                            </span>
                          </div>

                          {/* Verification matches */}
                          <div className="grid-3 mb-2" style={{ gap: 'var(--sp-2)', fontSize: '.76rem' }}>
                            <div>
                              Metrics match: {repro.metrics_match ? (
                                <span style={{ color: 'var(--clr-pass)', fontWeight: 600 }}>PASS</span>
                              ) : (
                                <span style={{ color: 'var(--clr-fail)', fontWeight: 600 }}>FAIL</span>
                              )}
                            </div>
                            <div>
                              Predictions match: {repro.predictions_match ? (
                                <span style={{ color: 'var(--clr-pass)', fontWeight: 600 }}>PASS</span>
                              ) : (
                                <span style={{ color: 'var(--clr-fail)', fontWeight: 600 }}>FAIL</span>
                              )}
                            </div>
                            <div>
                              Model intact: {repro.model_artifact_intact ? (
                                <span style={{ color: 'var(--clr-pass)', fontWeight: 600 }}>PASS</span>
                              ) : (
                                <span style={{ color: 'var(--clr-fail)', fontWeight: 600 }}>FAIL</span>
                              )}
                            </div>
                          </div>

                          {/* Comparison Table */}
                          {repro.original_metrics && repro.reproduced_metrics && (
                            <table style={{ width: '100%', fontSize: '.74rem', marginTop: 'var(--sp-2)' }}>
                              <thead>
                                <tr>
                                  <th style={{ textAlign: 'left', padding: '2px 4px' }}>Metric</th>
                                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>Original</th>
                                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>Reproduced</th>
                                  <th style={{ textAlign: 'center', padding: '2px 4px' }}>Match</th>
                                </tr>
                              </thead>
                              <tbody>
                                {Object.keys(repro.original_metrics).map((m) => {
                                  const orig = repro.original_metrics[m];
                                  const rep = repro.reproduced_metrics[m];
                                  const match = orig === rep;
                                  return (
                                    <tr key={m}>
                                      <td style={{ padding: '2px 4px' }}>{m}</td>
                                      <td style={{ textAlign: 'right', padding: '2px 4px' }}>{orig}</td>
                                      <td style={{ textAlign: 'right', padding: '2px 4px' }}>{rep}</td>
                                      <td style={{ textAlign: 'center', padding: '2px 4px' }}>
                                        {match ? (
                                          <Check size={12} style={{ color: 'var(--clr-pass)' }} />
                                        ) : (
                                          <XCircle size={12} style={{ color: 'var(--clr-fail)' }} />
                                        )}
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
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
