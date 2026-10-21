import { Link } from 'react-router-dom';
import { Inbox } from 'lucide-react';

export default function EmptyState({
  icon: Icon = Inbox,
  title = 'No records found',
  desc,
  actionLabel,
  actionHref,
  onAction,
}) {
  return (
    <div
      className="empty-state"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 'var(--sp-3)',
        padding: 'var(--sp-8) var(--sp-4)',
        color: 'var(--clr-text-3)',
        textAlign: 'center',
      }}
    >
      <Icon size={36} strokeWidth={1.3} style={{ color: 'var(--clr-text-3)' }} />
      <p style={{ fontWeight: 600, color: 'var(--clr-text)', fontSize: 'var(--text-base)', margin: 0 }}>
        {title}
      </p>
      {desc && (
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--clr-text-2)', maxWidth: 440, margin: 0 }}>
          {desc}
        </p>
      )}
      {actionLabel && actionHref && (
        <Link to={actionHref} className="btn btn-primary btn-sm" style={{ marginTop: 'var(--sp-2)' }}>
          {actionLabel}
        </Link>
      )}
      {actionLabel && onAction && !actionHref && (
        <button
          type="button"
          onClick={onAction}
          className="btn btn-primary btn-sm"
          style={{ marginTop: 'var(--sp-2)' }}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

