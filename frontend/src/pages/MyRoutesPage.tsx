/**
 * A worker's own recorded routes.
 *
 * Only routes they requested, filtered to their employee id in SQL on the server. A worker sees
 * why their own route was changed and which published alert caused it — both things they were
 * already shown at the time — and nothing about anyone else.
 *
 * Route history begins when recording was introduced. The page says so rather than letting an
 * empty list imply that no routes were ever taken.
 */
import { Crosshair, RefreshCw, ShieldAlert } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { useSettings } from '../context/SettingsContext';
import type { RouteEvent } from '../types/safety';

const STORAGE_KEY = 'ecosentinel.employeeId.v1';

const metres = (value: number | null | undefined) =>
  value == null ? '—' : value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${value} m`;

function remembered(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
}

export function MyRoutesPage() {
  const { api } = useSettings();
  const [employeeId, setEmployeeId] = useState(remembered);
  const [routes, setRoutes] = useState<RouteEvent[] | null>(null);
  const [note, setNote] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (id: string) => {
    const trimmed = id.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const body = await api.workerRoutes(trimmed);
      setRoutes(body.routes);
      setNote(body.note);
      try { window.localStorage.setItem(STORAGE_KEY, trimmed); } catch { /* optional */ }
    } catch (cause) {
      setRoutes(null);
      setError(cause instanceof Error ? cause.message : 'Could not load your routes.');
    } finally {
      setBusy(false);
    }
  }, [api]);

  useEffect(() => {
    const id = remembered();
    if (id) void load(id);
  }, [load]);

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <DashboardCard
        title="My Routes" subtitle="Routes you have requested" icon={Crosshair} iconColor="#2563eb"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={employeeId}
              onChange={(event) => setEmployeeId(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') void load(employeeId); }}
              placeholder="Employee ID — e.g. EMP001"
              aria-label="Employee ID"
              className="w-44 rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand/40"
            />
            <Button size="sm" variant="ghost" icon={RefreshCw} loading={busy}
                    onClick={() => void load(employeeId)}>Load</Button>
          </div>
        }
      >
        {error && (
          <p className="mb-2 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-xs text-risk-high">
            {error}
          </p>
        )}

        {routes === null && !error && (
          <p className="text-sm text-fg-muted">Enter your employee ID to see your recorded routes.</p>
        )}

        {routes?.length === 0 && (
          <p className="text-sm text-fg-muted">No recorded route event exists for you yet.</p>
        )}

        <ul className="space-y-2">
          {routes?.map((event) => (
            <li key={event.id}
                className={`rounded-lg border px-3 py-2.5 ${
                  event.routeAdjustedForSafety
                    ? 'border-risk-moderate/25 bg-risk-moderate/[0.06]'
                    : 'border-black/[0.06] bg-black/[0.02]'}`}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] font-semibold text-fg">
                  {metres(event.selectedDistanceMeters)}
                </span>
                <span className="font-mono text-[10px] text-fg-subtle">
                  {event.createdAt.slice(0, 16).replace('T', ' ')}
                </span>
              </div>

              {event.routeAdjustedForSafety ? (
                <>
                  <p className="mt-1 flex items-center gap-1.5 text-[11.5px] font-semibold text-risk-moderate">
                    <ShieldAlert className="size-3.5" /> Route adjusted for safety
                  </p>
                  <p className="mt-0.5 text-[11.5px] leading-relaxed text-fg-muted">
                    The shortest route ({metres(event.originalDistanceMeters)}) entered a published
                    safety-alert area. You were given a route that avoids it
                    {event.detourDistanceMeters > 0 &&
                      `, ${metres(event.detourDistanceMeters)} longer`}.
                  </p>
                </>
              ) : (
                <p className="mt-1 text-[11.5px] text-fg-muted">{event.classificationLabel}</p>
              )}

              {event.alert?.title && (
                <p className="mt-0.5 text-[11px] text-fg-subtle">
                  Published alert: {event.alert.title}
                </p>
              )}
            </li>
          ))}
        </ul>

        {note && (
          <p className="mt-3 rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2 text-[10.5px] leading-relaxed text-fg-subtle">
            {note}
          </p>
        )}
      </DashboardCard>
    </div>
  );
}
