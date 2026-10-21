import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  UploadCloud,
  Database,
  ShieldCheck,
  FlaskConical,
  BarChart2,
  Cpu,
  Sun,
  Moon,
  Link2,
} from 'lucide-react';
import ChainStatus from './components/ChainStatus';

const SECTIONS = ['Data', 'Integrity', 'ML & Analytics'];

const NAV = [
  { to: '/upload',       label: 'Upload',           icon: UploadCloud,  section: 'Data' },
  { to: '/explorer',     label: 'Dataset Explorer',  icon: Database,     section: 'Data' },
  { to: '/verify',       label: 'Verification',      icon: ShieldCheck,  section: 'Integrity' },
  { to: '/lab',          label: 'Tampering Lab',     icon: FlaskConical, section: 'Integrity' },
  { to: '/experiments',  label: 'ML Experiments',    icon: Cpu,          section: 'ML & Analytics' },
  { to: '/analytics',    label: 'Analytics',         icon: BarChart2,    section: 'ML & Analytics' },
];

export default function App() {
  const [theme, setTheme] = useState('dark');
  const location = useLocation();

  const toggle = () =>
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'));

  return (
    <div
      className="app-layout"
      data-theme={theme}
    >
      {/* Sidebar */}
      <aside className="app-sidebar" aria-label="Primary navigation">
        <div className="sidebar-brand">
          <div className="sidebar-brand-icon">
            <Link2 size={16} />
          </div>
          <div>
            <div className="sidebar-brand-name">ML Provenance</div>
            <div className="sidebar-brand-sub">Blockchain Integrity</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {SECTIONS.map((section) => {
            const items = NAV.filter((n) => n.section === section);
            return (
              <div key={section}>
                <div className="nav-section-label">{section}</div>
                {items.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
                    id={`nav-${to.replace('/', '')}`}
                    data-testid={`nav-${to.replace('/', '')}`}
                  >
                    <Icon size={15} className="nav-icon" />
                    {label}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={toggle}
            aria-label="Toggle light/dark theme"
            id="theme-toggle"
            style={{ width: '100%', justifyContent: 'center' }}
          >
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      </aside>

      {/* Header */}
      <header className="app-header">
        <span className="header-title">
          {NAV.find((n) => n.to === location.pathname)?.label ?? 'ML Provenance'}
        </span>
        <ChainStatus />
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={toggle}
          aria-label="Toggle theme"
          id="header-theme-toggle"
          style={{ marginLeft: 'var(--sp-2)' }}
        >
          {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
        </button>
      </header>

      {/* Main content — rendered by router */}
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
