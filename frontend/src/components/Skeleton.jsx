export function SkeletonText({ width = '100%', style = {} }) {
  return (
    <div
      className="skeleton skeleton-text"
      style={{ width, ...style }}
    />
  );
}

export function SkeletonCard() {
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <SkeletonText width="40%" />
      <SkeletonText width="70%" />
      <SkeletonText width="55%" />
    </div>
  );
}

export function SkeletonRows({ n = 4 }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Array.from({ length: n }).map((_, i) => (
        <SkeletonText key={i} width={`${60 + (i % 3) * 15}%`} />
      ))}
    </div>
  );
}
