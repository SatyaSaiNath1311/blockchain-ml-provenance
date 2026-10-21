import { CheckCircle2, XCircle, HelpCircle } from 'lucide-react';
import HashDisplay from './HashDisplay';

function CheckItem({ name, value }) {
  const cls = value === true ? 'pass' : value === false ? 'fail' : '';
  const Icon = value === true ? CheckCircle2 : value === false ? XCircle : HelpCircle;
  const color =
    value === true ? 'var(--clr-pass)' : value === false ? 'var(--clr-fail)' : 'var(--clr-text-3)';
  return (
    <div className={`check-item ${cls}`}>
      <Icon size={14} style={{ color, flexShrink: 0 }} />
      <span className="text-xs">
        {name.replace(/_/g, ' ')}
      </span>
      <span
        className="badge"
        style={{
          marginLeft: 'auto',
          background: color + '22',
          color,
          fontSize: '.6rem',
        }}
      >
        {value === null ? 'N/A' : value ? 'PASS' : 'FAIL'}
      </span>
    </div>
  );
}

export default function VerifyResult({ result }) {
  if (!result) return null;

  const { status, reason, checks = {}, details = {}, timings_ms = {} } = result;

  const verdictCls =
    status === 'VERIFIED'
      ? 'verdict-pass'
      : status === 'TAMPERING_DETECTED'
      ? 'verdict-fail'
      : 'verdict-na';

  const VerdictIcon =
    status === 'VERIFIED' ? CheckCircle2 : status === 'TAMPERING_DETECTED' ? XCircle : HelpCircle;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
      {/* Big badge */}
      <div>
        <div className={`verdict-badge ${verdictCls}`}>
          <VerdictIcon size={28} />
          {status === 'VERIFIED'
            ? 'PASS — File Intact'
            : status === 'TAMPERING_DETECTED'
            ? 'FAIL — Tampering Detected'
            : 'NOT VERIFIABLE'}
        </div>
        <p className="text-sm text-muted" style={{ marginTop: 'var(--sp-2)' }}>{reason}</p>
      </div>

      {/* Individual checks */}
      <div className="card" style={{ padding: 'var(--sp-4)' }}>
        <p className="text-xs text-faint" style={{ marginBottom: 'var(--sp-3)', textTransform: 'uppercase', letterSpacing: '.5px', fontWeight: 600 }}>
          Integrity Checks
        </p>
        <div className="checks-grid">
          {Object.entries(checks).map(([k, v]) => (
            <CheckItem key={k} name={k} value={v} />
          ))}
        </div>
      </div>

      {/* Hash comparison */}
      <div className="card" style={{ padding: 'var(--sp-4)' }}>
        <p className="text-xs text-faint" style={{ marginBottom: 'var(--sp-3)', textTransform: 'uppercase', letterSpacing: '.5px', fontWeight: 600 }}>
          Hash Comparison
        </p>
        <div className="grid-2" style={{ gap: 'var(--sp-4)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
            <HashDisplay label="Expected file hash (chain)" value={details.expected_file_hash} />
            <HashDisplay label="Actual file hash" value={details.actual_file_hash} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
            <HashDisplay label="Expected Merkle root (chain)" value={details.expected_merkle_root} />
            <HashDisplay label="Actual Merkle root" value={details.actual_merkle_root} />
          </div>
        </div>
      </div>

      {/* Changed chunks table */}
      {(details.changed_chunks?.length > 0 ||
        details.extra_chunks?.length > 0 ||
        details.missing_chunks?.length > 0) && (
        <div className="card" style={{ padding: 'var(--sp-4)' }}>
          <p className="text-xs text-faint" style={{ marginBottom: 'var(--sp-3)', textTransform: 'uppercase', letterSpacing: '.5px', fontWeight: 600 }}>
            Modified Chunks
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Chunk indices</th>
                </tr>
              </thead>
              <tbody>
                {details.changed_chunks?.length > 0 && (
                  <tr>
                    <td><span className="badge badge-fail">Changed</span></td>
                    <td className="mono">{details.changed_chunks.join(', ')}</td>
                  </tr>
                )}
                {details.extra_chunks?.length > 0 && (
                  <tr>
                    <td><span className="badge badge-warn">Extra</span></td>
                    <td className="mono">{details.extra_chunks.join(', ')}</td>
                  </tr>
                )}
                {details.missing_chunks?.length > 0 && (
                  <tr>
                    <td><span className="badge badge-info">Missing</span></td>
                    <td className="mono">{details.missing_chunks.join(', ')}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Timings */}
      <div style={{ display: 'flex', gap: 'var(--sp-3)', flexWrap: 'wrap' }}>
        {Object.entries(timings_ms).map(([k, v]) => (
          <div key={k} className="badge badge-neutral">
            {k.replace(/_ms$/, '')}: {v} ms
          </div>
        ))}
      </div>
    </div>
  );
}
