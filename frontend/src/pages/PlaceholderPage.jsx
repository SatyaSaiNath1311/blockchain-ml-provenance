import { Construction } from 'lucide-react';

export default function PlaceholderPage({ title = 'Coming soon', desc }) {
  return (
    <div className="page-container">
      <div className="page-header">
        <h1 className="page-title">{title}</h1>
        {desc && <p className="page-desc">{desc}</p>}
      </div>
      <div className="card" style={{ maxWidth: 480, padding: 'var(--sp-12)', textAlign: 'center' }}>
        <Construction size={40} style={{ color: 'var(--clr-text-3)', margin: '0 auto' }} />
        <p style={{ marginTop: 'var(--sp-4)', fontWeight: 600, color: 'var(--clr-text-2)' }}>
          Task B — Coming in the next sprint
        </p>
        <p className="text-sm text-faint" style={{ marginTop: 'var(--sp-2)' }}>
          This page will host ML experiment analytics and Playwright tests.
        </p>
      </div>
    </div>
  );
}
