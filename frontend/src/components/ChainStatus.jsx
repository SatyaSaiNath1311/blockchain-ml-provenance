import { useEffect, useState } from 'react';
import { Activity, WifiOff } from 'lucide-react';
import { health } from '../api/client';

export default function ChainStatus() {
  const [state, setState] = useState('loading'); // loading | online | offline

  useEffect(() => {
    let cancelled = false;
    const check = () => {
      health()
        .then(() => {
          if (!cancelled) {
            setState('online');
          }
        })
        .catch(() => {
          if (!cancelled) setState('offline');
        });
    };
    check();
    const iv = setInterval(check, 15_000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, []);

  return (
    <div className="chain-status">
      <span className={`status-dot ${state}`} />
      {state === 'loading' && <span className="text-faint">Connecting…</span>}
      {state === 'online' && (
        <>
          <Activity size={14} style={{ color: 'var(--clr-pass)' }} />
          <span>Chain connected</span>
        </>
      )}
      {state === 'offline' && (
        <>
          <WifiOff size={14} style={{ color: 'var(--clr-fail)' }} />
          <span style={{ color: 'var(--clr-fail)' }}>Chain offline</span>
        </>
      )}
    </div>
  );
}
