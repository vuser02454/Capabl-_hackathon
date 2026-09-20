/**
 * Worker Route Intelligence — every recorded routing decision, and the evidence behind it.
 *
 * The screen exists to answer two questions an admin actually has after publishing an alert:
 * who came near it, and who was sent a different way. Both are answered from stored route
 * geometry recorded at the time, never from a route recomputed now — a rebuilt route would
 * reflect today's map and today's alerts, which is precisely what historical evidence must not do.
 *
 * When a detour is selected the map draws BOTH routes, because "this worker was rerouted" is a
 * claim that should be visible rather than asserted: the rejected shortest route in grey, the
 * route actually served in green, and the hazard circle they had to get around.
 */
import { AlertTriangle, Navigation, RefreshCw, Route as RouteIcon, ShieldAlert, Users } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { SafetyMap, type MapMarker, type RouteLine } from '../components/safety/SafetyMap';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { useSettings } from '../context/SettingsContext';
import type { AdminRoutesResponse, RouteClassification, RouteEvent } from '../types/safety';

const CLASSIFICATION_TONE: Record<RouteClassification, string> = {
  NORMAL_ROUTE: 'border-risk-low/25 bg-risk-low/10 text-risk-low',
  MODERATE_HAZARD_PASSED: 'border-risk-moderate/25 bg-risk-moderate/10 text-risk-moderate',
  HIGH_HAZARD_DETOUR: 'border-risk-high/25 bg-risk-high/10 text-risk-high',
  NO_SAFE_ALTERNATIVE: 'border-risk-high/40 bg-risk-high/[0.14] text-risk-high',
};

/** Route colour carries the outcome, so the map agrees with the table rather than repeating it. */
const ROUTE_COLOR: Record<RouteClassification, string> = {
  NORMAL_ROUTE: '#2563eb',
  MODERATE_HAZARD_PASSED: '#d97706',
  HIGH_HAZARD_DETOUR: '#059669',
  NO_SAFE_ALTERNATIVE: '#dc2626',
};

const metres = (value: number | null | undefined) =>
  value == null ? '—' : value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${value} m`;

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
      <p className="text-[22px] leading-none font-semibold text-fg">{value}</p>
      <p className="mt-1 text-[11px] text-fg-muted">{label}</p>
      {hint && <p className="mt-0.5 text-[10px] text-fg-subtle">{hint}</p>}
    </div>
  );
}

export function WorkerRoutesPage() {
  const { api } = useSettings();
  const [data, setData] = useState<AdminRoutesResponse | null>(null);
  const [selected, setSelected] = useState<RouteEvent | null>(null);
  const [employeeId, setEmployeeId] = useState('');
  const [classification, setClassification] = useState('');
  const [department, setDepartment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await api.adminRoutes({
        employeeId: employeeId.trim() || undefined,
        classification: classification || undefined,
        department: department || undefined,
      }));
      setSelected(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load route events.');
    } finally {
      setBusy(false);
    }
  }, [api, employeeId, classification, department]);

  useEffect(() => { void load(); }, [load]);

  /* A detour draws two lines. The rejected shortest route is dashed and grey so it reads as
     "what would have happened", and the served route is solid in its outcome colour. */
  const routeLines: RouteLine[] = useMemo(() => {
    if (!selected) return [];
    const lines: RouteLine[] = [];
    if (selected.routeAdjustedForSafety && selected.originalRouteGeometry.length > 1) {
      lines.push({
        id: 'original',
        positions: selected.originalRouteGeometry.map((p) => [p.latitude, p.longitude] as [number, number]),
        color: '#64748b', dashed: true,
      });
    }
    if (selected.selectedRouteGeometry.length > 1) {
      lines.push({
        id: 'selected',
        positions: selected.selectedRouteGeometry.map((p) => [p.latitude, p.longitude] as [number, number]),
        color: ROUTE_COLOR[selected.classification], emphasis: true,
      });
    }
    return lines;
  }, [selected]);

  const markers: MapMarker[] = useMemo(() => {
    if (!selected) return [];
    const out: MapMarker[] = [
      { id: 'start', latitude: selected.start.latitude, longitude: selected.start.longitude,
        kind: 'start', title: 'Start' },
      { id: 'destination', latitude: selected.destination.latitude,
        longitude: selected.destination.longitude, kind: 'destination', title: 'Destination' },
    ];
    if (selected.alert?.latitude != null && selected.alert.longitude != null) {
      out.push({
        id: `alert-${selected.alert.id}`, latitude: selected.alert.latitude,
        longitude: selected.alert.longitude, kind: 'published',
        title: `⚠ ${selected.alert.title}`,
        body: `${selected.alert.severity ?? ''} · closest approach ${metres(selected.alert.minimumDistanceMeters)}`,
        radiusMeters: selected.alert.radiusMeters ?? undefined,
      });
    }
    return out;
  }, [selected]);

  const bounds = selected?.selectedRouteGeometry.length
    ? [...selected.selectedRouteGeometry, ...selected.originalRouteGeometry]
        .map((p) => [p.latitude, p.longitude] as [number, number])
    : null;

  return (
    <div className="space-y-4">
      <DashboardCard
        title="Worker Route Intelligence"
        subtitle="Routing decisions recorded when a worker requested a route"
        icon={RouteIcon}
        iconColor="#2563eb"
        actions={<Button size="sm" variant="ghost" icon={RefreshCw} loading={busy}
                         onClick={() => void load()}>Refresh</Button>}
      >
        {error && <p className="mb-2 text-xs text-risk-high">{error}</p>}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Route events" value={data.summary.total} />
              <Stat label="Normal routes" value={data.summary.normal} />
              <Stat label="Passed a hazard" value={data.summary.moderateHazard} />
              <Stat label="High-hazard detours" value={data.summary.highHazardDetour} />
              <Stat label="No safe alternative" value={data.summary.noSafeAlternative} />
              <Stat label="Workers affected" value={data.summary.workersAffected}
                    hint={`${data.summary.alertsInvolved} alert(s)`} />
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                value={employeeId}
                onChange={(event) => setEmployeeId(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') void load(); }}
                placeholder="Employee ID"
                aria-label="Filter by employee ID"
                className="w-36 rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand/40"
              />
              <select
                value={classification}
                onChange={(event) => setClassification(event.target.value)}
                aria-label="Filter by classification"
                className="rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand/40"
              >
                <option value="">All classifications</option>
                {data.classifications.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
              <select
                value={department}
                onChange={(event) => setDepartment(event.target.value)}
                aria-label="Filter by department"
                className="rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand/40"
              >
                <option value="">All departments</option>
                {data.departments.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <Button size="sm" variant="ghost" onClick={() => void load()}>Apply</Button>
            </div>

            {/* Said plainly wherever these numbers appear: the history starts when recording did. */}
            <p className="mt-2 text-[10.5px] leading-relaxed text-fg-subtle">
              {data.summary.coverageNote}
            </p>
          </>
        )}
      </DashboardCard>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.2fr)]">
        <DashboardCard title="Route events" subtitle={`${data?.count ?? 0} recorded`}
                       icon={Navigation} iconColor="#7c3aed">
          {data?.count === 0 && (
            <p className="text-xs text-fg-muted">
              No recorded route event matches these filters.
            </p>
          )}
          <ul className="max-h-[60vh] space-y-1.5 overflow-y-auto pr-1">
            {data?.routes.map((event) => (
              <li key={event.id}>
                <button type="button" onClick={() => setSelected(event)}
                        className="w-full rounded-lg border border-black/[0.06] bg-black/[0.02] px-2.5 py-2 text-left transition hover:border-brand/30">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-[10.5px] text-fg-subtle">
                      RE-{event.id} · {event.employeeId ?? 'unattributed'}
                    </span>
                    <span className={`rounded-full border px-2 py-0.5 text-[9.5px] font-semibold tracking-wider uppercase ${CLASSIFICATION_TONE[event.classification]}`}>
                      {event.classificationLabel}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11.5px] text-fg-muted">
                    {metres(event.selectedDistanceMeters)}
                    {event.routeAdjustedForSafety &&
                      ` · +${metres(event.detourDistanceMeters)} (${event.detourRatio}×)`}
                  </p>
                  <p className="font-mono text-[10px] text-fg-subtle">
                    {event.createdAt.slice(0, 16).replace('T', ' ')}
                    {event.workerName && ` · ${event.workerName}`}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </DashboardCard>

        {selected && (
          <DashboardCard
            title={`Route event RE-${selected.id}`}
            subtitle={selected.selectedReason ?? selected.classificationLabel}
            icon={selected.routeAdjustedForSafety ? ShieldAlert : Navigation}
            iconColor={selected.routeAdjustedForSafety ? '#dc2626' : '#2563eb'}
            actions={
              <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-wider uppercase ${CLASSIFICATION_TONE[selected.classification]}`}>
                {selected.classificationLabel}
              </span>
            }
          >
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
              <dt className="text-fg-subtle">Worker</dt>
              <dd className="text-fg">{selected.employeeId ?? 'unattributed'}
                {selected.workerName && ` · ${selected.workerName}`}</dd>
              <dt className="text-fg-subtle">Requested</dt>
              <dd className="text-fg">{selected.createdAt.slice(0, 16).replace('T', ' ')}</dd>
              <dt className="text-fg-subtle">Original distance</dt>
              <dd className="text-fg">{metres(selected.originalDistanceMeters)}</dd>
              <dt className="text-fg-subtle">Selected distance</dt>
              <dd className="text-fg">{metres(selected.selectedDistanceMeters)}</dd>
              {selected.routeAdjustedForSafety && (
                <>
                  <dt className="text-fg-subtle">Additional</dt>
                  <dd className="text-fg">{metres(selected.detourDistanceMeters)}</dd>
                  <dt className="text-fg-subtle">Detour ratio</dt>
                  <dd className="text-fg">{selected.detourRatio}×</dd>
                </>
              )}
              {selected.alert && (
                <>
                  <dt className="text-fg-subtle">Hazard</dt>
                  <dd className="text-fg">{selected.alert.title} ({selected.alert.severity})</dd>
                  <dt className="text-fg-subtle">Closest approach</dt>
                  <dd className="text-fg">{metres(selected.alert.minimumDistanceMeters)}</dd>
                  <dt className="text-fg-subtle">Hazard radius</dt>
                  <dd className="text-fg">{metres(selected.alert.radiusMeters)}</dd>
                </>
              )}
            </dl>

            <div className="mt-3">
              <SafetyMap markers={markers}
                         center={[selected.start.latitude, selected.start.longitude]}
                         zoom={13} height={360} routes={routeLines} fitBounds={bounds} />
            </div>

            {selected.routeAdjustedForSafety && (
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="flex items-center gap-1.5 text-[10.5px] text-fg-subtle">
                  <span className="h-[3px] w-5 rounded-full bg-[#64748b]" /> Rejected shortest route
                </span>
                <span className="flex items-center gap-1.5 text-[10.5px] text-fg-subtle">
                  <span className="h-[3px] w-5 rounded-full"
                        style={{ background: ROUTE_COLOR[selected.classification] }} /> Route served
                </span>
              </div>
            )}

            {selected.classification === 'NO_SAFE_ALTERNATIVE' && (
              <p className="mt-2 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-[11.5px] text-risk-high">
                <AlertTriangle className="mr-1 inline size-3" />
                No alternative avoided the published alert. The worker was shown this route with
                the hazard flagged on it.
              </p>
            )}

            <p className="mt-2 text-[10.5px] leading-relaxed text-fg-subtle">
              <Users className="mr-1 inline size-3" />
              Geometry shown is the route recorded when it was served, not a route recalculated now.
            </p>
          </DashboardCard>
        )}
      </div>
    </div>
  );
}
