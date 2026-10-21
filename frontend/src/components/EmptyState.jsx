import { Inbox } from 'lucide-react';

export default function EmptyState({ icon: Icon = Inbox, title = 'Nothing here', desc }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 'var(--sp-3)',
        padding: 'var(--sp-12)',
        color: 'var(--clr-text-3)',
        textAlign: 'center',
      }}
    >
      <Icon size={36} strokeWidth={1.2} />
      <p style={{ fontWeight: 600, color: 'var(--clr-text-2)', fontSize: '.9rem' }}>{title}</p>
      {desc && <p style={{ fontSize: '.8rem' }}>{desc}</p>}
    </div>
  );
}
