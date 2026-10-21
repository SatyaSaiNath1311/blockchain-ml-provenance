import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

export default function ShortId({
  id,
  length = 8,
  mono = true,
  copyable = true,
  style = {},
}) {
  const [copied, setCopied] = useState(false);

  if (!id) return <span className="text-faint">—</span>;

  let shortText = id;
  if (id.length > length) {
    const front = Math.max(4, Math.ceil(length / 2));
    const back = Math.max(4, Math.floor(length / 2));
    shortText = id.length > front + back + 2 ? `${id.slice(0, front)}…${id.slice(-back)}` : id;
  }

  const onCopy = (e) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(id).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };

  return (
    <span
      className="short-id"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        verticalAlign: 'middle',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      <span
        className={mono ? 'mono' : ''}
        title={id}
        style={{
          fontFamily: mono ? 'var(--font-mono)' : 'inherit',
          fontVariantNumeric: 'tabular-nums',
          whiteSpace: 'nowrap',
        }}
      >
        {shortText}
      </span>
      {copyable && (
        <button
          type="button"
          onClick={onCopy}
          aria-label={`Copy ID ${id}`}
          title="Copy full ID"
          style={{
            background: 'transparent',
            border: 'none',
            color: copied ? 'var(--clr-pass)' : 'var(--clr-text-3)',
            cursor: 'pointer',
            padding: '2px',
            display: 'inline-flex',
            alignItems: 'center',
            borderRadius: '4px',
            lineHeight: 1,
          }}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
        </button>
      )}
    </span>
  );
}
