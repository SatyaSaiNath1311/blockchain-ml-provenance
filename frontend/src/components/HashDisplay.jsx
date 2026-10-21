import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

function truncateMiddle(str, front = 12, back = 10) {
  if (!str) return '';
  if (typeof str !== 'string') str = String(str);
  if (str.length <= front + back + 3) return str;
  return `${str.slice(0, front)}…${str.slice(-back)}`;
}

export default function HashDisplay({ label, value }) {
  const [copied, setCopied] = useState(false);

  if (!value) return <span className="text-faint">—</span>;

  const onCopy = () => {
    navigator.clipboard?.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };

  const displayVal = truncateMiddle(value, 12, 10);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {label && <span className="text-xs text-faint">{label}</span>}
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
        <span
          className="hash"
          title={value}
          style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}
        >
          {displayVal}
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onCopy}
          aria-label={`Copy ${label || 'value'}`}
          title={`Copy full value: ${value}`}
          style={{ padding: 'var(--sp-1) var(--sp-3)', fontSize: 'var(--text-xs)', flexShrink: 0 }}
        >
          {copied ? <Check size={14} style={{ color: 'var(--clr-pass)' }} /> : <Copy size={14} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </div>
  );
}

