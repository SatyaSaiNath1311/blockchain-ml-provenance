export default function HashDisplay({ label, value }) {
  if (!value) return <span className="text-faint">—</span>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {label && <span className="text-xs text-faint">{label}</span>}
      <span className="hash">{value}</span>
    </div>
  );
}
