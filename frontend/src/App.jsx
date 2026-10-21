import { useState, useEffect } from 'react';
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
  { to: '/upload',       label: 'Upload dataset',           icon: UploadCloud,  section: 'Data' },
  { to: '/explorer',     label: 'Dataset explorer',         icon: Database,     section: 'Data' },
  { to: '/verify',       label: 'Verification',             icon: ShieldCheck,  section: 'Integrity' },
  { to: '/lab',          label: 'Tampering lab',            icon: FlaskConical, section: 'Integrity' },
  { to: '/experiments',  label: 'ML experiments',           icon: Cpu,          section: 'ML & Analytics' },
  { to: '/analytics',    label: 'Analytics',                icon: BarChart2,    section: 'ML & Analytics' },
];

export default function App() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem('theme') || 'dark';
    } catch {
      return 'dark';
    }
  });
  const location = useLocation();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('theme', theme);
    } catch {}
  }, [theme]);

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
            <Link2 size={18} />
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
              <div key={section} className="nav-group">
                <div className="nav-section-label">{section}</div>
                {items.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
                    id={`nav-${to.replace('/', '')}`}
                    data-testid={`nav-${to.replace('/', '')}`}
                  >
                    <Icon size={18} className="nav-icon" />
                    <span className="nav-label">{label}</span>
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <button
            type="button"
            className="sidebar-theme-toggle"
            onClick={toggle}
            aria-label="Toggle light/dark theme"
            id="theme-toggle"
          >
            {theme === 'dark' ? <Sun size={18} className="nav-icon" /> : <Moon size={18} className="nav-icon" />}
            <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
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

      {/* Mobile and tablet navigation bar */}
      <nav className="mobile-nav-bar" aria-label="Tablet navigation">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            style={{ padding: '6px var(--sp-3)', fontSize: 'var(--text-xs)', whiteSpace: 'nowrap' }}
          >
            <Icon size={16} className="nav-icon" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Main content — rendered by router */}
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
