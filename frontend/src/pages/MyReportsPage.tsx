/**
 * A worker's own report history.
 *
 * The only new screen this change adds. It shows what the worker filed, where, and how it was
 * classified — nothing about review, no reviewer, no internal reasoning, and nothing belonging to
 * anyone else. That is enforced server-side: `/api/worker/reports` filters to the worker's own
 * rows in SQL, so there is no client-side filter here that could drift out of step.
 *
 * Identity is a typed employee id because this project has no login. The page says so rather than
 * presenting the field as if it were a sign-in, and the id is remembered per browser only as a
 * convenience.
 */
import { AlertTriangle, FileText, Image as ImageIcon, MapPin, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { SafetyMap, type MapMarker } from '../components/safety/SafetyMap';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { Chip } from '../components/ui/primitives';
import { RiskBadge } from '../components/ui/RiskBadge';
import { useSettings } from '../context/SettingsContext';
import { toDisplayRisk, type MyReport, type WorkerProfile } from '../types/safety';

/** Remembered so the demo does not require retyping an id on every visit. Not a session. */
const STORAGE_KEY = 'ecosentinel.employeeId.v1';

const SOURCE_LABEL: Record<string, string> = {
  browser_gps: 'Device GPS',
  text_search: 'Location search',
  manual_map: 'Selected on map',
  demo_seed: 'Demo seed data',
  unknown: 'Not recorded',
};

function remembered(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? '';
  } catch {
    return ''; // private browsing / blocked storage — the page still works, just unfilled
  }
}

export function MyReportsPage() {
  const { api } = useSettings();
  const [employeeId, setEmployeeId] = useState(remembered);
  const [worker, setWorker] = useState<WorkerProfile | null>(null);
  const [reports, setReports] = useState<MyReport[]>([]);
  const [open, setOpen] = useState<MyReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (id: string) => {
    const trimmed = id.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const body = await api.myReports(trimmed);
      setWorker(body.worker);
      setReports(body.reports);
      setOpen(null);
      try { window.localStorage.setItem(STORAGE_KEY, trimmed); } catch { /* optional */ }
    } catch (cause) {
      setWorker(null);
      setReports([]);
      setError(cause instanceof Error ? cause.message : 'Could not load your reports.');
    } finally {
      setBusy(false);
    }
  }, [api]);

  // Load once if an id was remembered; never prompt for one on its own initiative.
  useEffect(() => {
    const id = remembered();
    if (id) void load(id);
  }, [load]);

  const markers: MapMarker[] = open && open.latitude !== null && open.longitude !== null
    ? [{ id: open.id, latitude: open.latitude, longitude: open.longitude, kind: 'report',
         title: `Report SR-${open.id}`, body: open.location ?? undefined }]
    : [];

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <DashboardCard
        title="My Reports"
        subtitle={worker ? `${worker.name} · ${worker.department ?? 'No department'}` : 'Your submitted safety reports'}
        icon={FileText}
        iconColor="#2563eb"
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
                    onClick={() => void load(employeeId)}>
              Load
            </Button>
          </div>
        }
      >
        {error && (
          <p className="mb-2 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-xs text-risk-high">
            {error}
          </p>
        )}

        {!worker && !error && (
          <p className="text-sm text-fg-muted">
            Enter your employee ID to see the reports you have submitted.
          </p>
        )}

        {worker && reports.length === 0 && (
          <p className="text-sm text-fg-muted">You have not submitted any reports yet.</p>
        )}

        <ul className="space-y-2">
          {reports.map((report) => (
            <li key={report.id}>
              <button
                type="button"
                onClick={() => setOpen(open?.id === report.id ? null : report)}
                className="w-full rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5 text-left transition hover:border-brand/30"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono text-[10.5px] text-fg-subtle">SR-{report.id}</span>
                  <span className="flex items-center gap-1.5">
                    {report.hasPhoto && <ImageIcon className="size-3 text-fg-subtle" aria-label="Photo attached" />}
                    {report.latitude !== null && <MapPin className="size-3 text-fg-subtle" aria-label="Has a location" />}
                    {report.riskLevel && <RiskBadge level={toDisplayRisk(report.riskLevel)} size="sm" />}
                  </span>
                </div>
                <p className="mt-1 text-[12.5px] leading-relaxed text-fg">{report.reportText}</p>
                <p className="mt-1 font-mono text-[10px] text-fg-subtle">
                  {report.createdAt.slice(0, 16).replace('T', ' ')}
                  {report.location && ` · ${report.location}`}
                  {report.status && ` · ${report.status}`}
                </p>
              </button>

              {open?.id === report.id && (
                <div className="mt-1.5 rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
                  {report.hazards.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      {report.hazards.map((hazard) => <Chip key={hazard}>{hazard}</Chip>)}
                    </div>
                  )}
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
                    <dt className="text-fg-subtle">Submitted</dt>
                    <dd className="text-fg">{report.createdAt.slice(0, 16).replace('T', ' ')}</dd>
                    <dt className="text-fg-subtle">Location source</dt>
                    <dd className="text-fg">
                      {SOURCE_LABEL[report.locationSource ?? 'unknown'] ?? report.locationSource}
                    </dd>
                    {report.latitude !== null && (
                      <>
                        <dt className="text-fg-subtle">Coordinates</dt>
                        <dd className="font-mono text-fg">
                          {report.latitude.toFixed(5)}, {report.longitude?.toFixed(5)}
                        </dd>
                      </>
                    )}
                    {report.gpsAccuracy !== null && (
                      <>
                        <dt className="text-fg-subtle">GPS accuracy</dt>
                        <dd className="text-fg">±{Math.round(report.gpsAccuracy)} m</dd>
                      </>
                    )}
                    <dt className="text-fg-subtle">Photo</dt>
                    <dd className="text-fg">{report.hasPhoto ? 'Attached' : 'None'}</dd>
                  </dl>

                  {report.latitude !== null && report.longitude !== null && (
                    <div className="mt-2">
                      <SafetyMap markers={markers}
                                 center={[report.latitude, report.longitude]}
                                 zoom={16} height={200}
                                 recenterTo={[report.latitude, report.longitude]} />
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>

        {worker && (
          <p className="mt-3 rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2 text-[10.5px] leading-relaxed text-fg-subtle">
            <AlertTriangle className="mr-1 inline size-3" />
            This demo has no login. The employee ID selects whose records to show and is not a
            sign-in — a real deployment would authenticate you first. You can only see your own
            reports; other workers' reports and internal review notes are never sent here.
          </p>
        )}
      </DashboardCard>
    </div>
  );
}
