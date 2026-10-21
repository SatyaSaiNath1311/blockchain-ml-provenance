import { CheckCircle2, XCircle, HelpCircle } from 'lucide-react';
import HashDisplay from './HashDisplay';
import ShortId from './ShortId';

function CheckItem({ name, value }) {
  const cls = value === true ? 'pass' : value === false ? 'fail' : '';
  const Icon = value === true ? CheckCircle2 : value === false ? XCircle : HelpCircle;
  const color =
    value === true ? 'var(--clr-pass)' : value === false ? 'var(--clr-fail)' : 'var(--clr-text-3)';
  return (
    <div className={`check-item ${cls}`}>
      <Icon size={16} style={{ color, flexShrink: 0 }} />
      <span className="text-xs">
        {name.replace(/_/g, ' ')}
      </span>
      <span
        className={`badge ${value === true ? 'badge-pass' : value === false ? 'badge-fail' : 'badge-neutral'}`}
        style={{
          marginLeft: 'auto',
          fontSize: 'var(--text-xs)',
          padding: 'var(--sp-1) var(--sp-3)',
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

  // Determine total chunks to render in visualization grid
  const allChunkIndices = [
    ...(details.changed_chunks || []),
    ...(details.extra_chunks || []),
    ...(details.missing_chunks || []),
  ];
  const maxIdx = allChunkIndices.length ? Math.max(...allChunkIndices) : 0;
  const totalChunks = Math.max(
    Number(details.actual_num_chunks || 0),
    Number(details.expected_num_chunks || 0),
    maxIdx + 1,
    1,
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
      {/* Big verdict badge card with thin colored left border */}
      <div
        className={`card ${status === 'VERIFIED' ? 'card-pass' : status === 'TAMPERING_DETECTED' ? 'card-fail' : 'card-warn'}`}
        style={{ padding: 'var(--sp-4)' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--sp-3)' }}>
          <div className={`verdict-badge ${verdictCls}`}>
            <VerdictIcon size={24} />
            <span>
              {status === 'VERIFIED'
                ? 'PASS — File Intact'
                : status === 'TAMPERING_DETECTED'
                ? 'FAIL — Tampering Detected'
                : 'NOT VERIFIABLE'}
            </span>
          </div>
          {timings_ms?.total_ms != null && (
            <span className="badge badge-neutral">
              Verified in {Number(timings_ms.total_ms).toFixed(1)} ms
            </span>
          )}
        </div>
        <p className="text-sm text-muted" style={{ marginTop: 'var(--sp-2)', marginBottom: 0 }}>{reason}</p>
      </div>

      {/* Individual checks */}
      <div className={`card ${status === 'VERIFIED' ? 'card-pass' : status === 'TAMPERING_DETECTED' ? 'card-fail' : ''}`} style={{ padding: 'var(--sp-4)' }}>
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
        {details.matches_version_id && (
          <div className="alert alert-warn mt-3" style={{ fontSize: 'var(--text-xs)' }}>
            <span>Rollback detected: file hash matches historical version:</span>
            <ShortId id={details.matches_version_id} />
          </div>
        )}
      </div>

      {/* Modified chunks table & visual chunk grid side-by-side */}
      {(details.changed_chunks?.length > 0 ||
        details.extra_chunks?.length > 0 ||
        details.missing_chunks?.length > 0) && (
        <div className="card" style={{ padding: 'var(--sp-4)' }}>
          <p className="text-xs text-faint" style={{ marginBottom: 'var(--sp-3)', textTransform: 'uppercase', letterSpacing: '.5px', fontWeight: 600 }}>
            Modified Chunks & Localization
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 'var(--sp-4)', alignItems: 'start' }}>
            {/* Table */}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ padding: 'var(--sp-3) var(--sp-4)' }}>Type</th>
                    <th style={{ padding: 'var(--sp-3) var(--sp-4)' }}>Chunk indices</th>
                  </tr>
                </thead>
                <tbody>
                  {details.changed_chunks?.length > 0 && (
                    <tr>
                      <td style={{ padding: 'var(--sp-3) var(--sp-4)' }}>
                        <span className="badge badge-fail">Changed</span>
                      </td>
                      <td className="mono" style={{ padding: 'var(--sp-3) var(--sp-4)', wordBreak: 'break-word' }}>
                        {details.changed_chunks.join(', ')}
                      </td>
                    </tr>
                  )}
                  {details.extra_chunks?.length > 0 && (
                    <tr>
                      <td style={{ padding: 'var(--sp-3) var(--sp-4)' }}>
                        <span className="badge badge-warn">Extra</span>
                      </td>
                      <td className="mono" style={{ padding: 'var(--sp-3) var(--sp-4)', wordBreak: 'break-word' }}>
                        {details.extra_chunks.join(', ')}
                      </td>
                    </tr>
                  )}
                  {details.missing_chunks?.length > 0 && (
                    <tr>
                      <td style={{ padding: 'var(--sp-3) var(--sp-4)' }}>
                        <span className="badge badge-info">Missing</span>
                      </td>
                      <td className="mono" style={{ padding: 'var(--sp-3) var(--sp-4)', wordBreak: 'break-word' }}>
                        {details.missing_chunks.join(', ')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Visual Chunk Grid */}
            <div style={{ background: 'var(--clr-surface-2)', padding: 'var(--sp-4)', borderRadius: 'var(--radius)', border: '1px solid var(--clr-border-faint)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--sp-3)' }}>
                <span className="text-xs text-muted" style={{ fontWeight: 600 }}>Chunk Map</span>
                <span className="text-xs text-faint">{totalChunks} chunks</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', maxHeight: '180px', overflowY: 'auto', padding: '2px' }}>
                {Array.from({ length: totalChunks }).map((_, idx) => {
                  const isChanged = details.changed_chunks?.includes(idx);
                  const isExtra = details.extra_chunks?.includes(idx);
                  const isMissing = details.missing_chunks?.includes(idx);

                  let bg = 'rgba(34,197,94,.12)';
                  let borderColor = 'rgba(34,197,94,.3)';
                  let color = 'var(--clr-pass)';
                  let statusText = 'Intact';

                  if (isChanged) {
                    bg = 'var(--clr-fail)';
                    borderColor = 'var(--clr-fail)';
                    color = '#ffffff';
                    statusText = 'Changed';
                  } else if (isExtra) {
                    bg = 'var(--clr-warn)';
                    borderColor = 'var(--clr-warn)';
                    color = '#000000';
                    statusText = 'Extra';
                  } else if (isMissing) {
                    bg = 'var(--clr-info)';
                    borderColor = 'var(--clr-info)';
                    color = '#000000';
                    statusText = 'Missing';
                  }

                  return (
                    <div
                      key={idx}
                      title={`Chunk ${idx}: ${statusText}`}
                      style={{
                        minWidth: '28px',
                        height: '28px',
                        padding: '0 4px',
                        borderRadius: '4px',
                        background: bg,
                        border: `1px solid ${borderColor}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '13px',
                        fontWeight: 600,
                        color,
                        fontFamily: 'var(--font-mono)',
                        cursor: 'default',
                        flexShrink: 0,
                      }}
                    >
                      {idx}
                    </div>
                  );
                })}
              </div>
              <div style={{ display: 'flex', gap: 'var(--sp-3)', marginTop: 'var(--sp-3)', fontSize: 'var(--text-xs)', color: 'var(--clr-text-2)' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: 'var(--clr-fail)' }} /> Changed
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: 'rgba(34,197,94,.2)', border: '1px solid var(--clr-pass)' }} /> Intact
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Timings */}
      <div style={{ display: 'flex', gap: 'var(--sp-3)', flexWrap: 'wrap', marginTop: 'var(--sp-5)', paddingTop: 'var(--sp-4)', borderTop: '1px solid var(--clr-border-faint)' }}>
        {Object.entries(timings_ms).map(([k, v]) => (
          <div key={k} className="badge badge-neutral" style={{ padding: 'var(--sp-2) var(--sp-3)', fontSize: 'var(--text-xs)' }}>
            {k.replace(/_ms$/, '')}: {v} ms
          </div>
        ))}
      </div>
    </div>
  );
}
