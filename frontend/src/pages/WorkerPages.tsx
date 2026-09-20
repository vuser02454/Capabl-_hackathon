/**
 * Worker experience: report an issue, see published alerts, see them on a map.
 *
 * A worker sees published safety alerts and nothing else — no raw reports, no reporter identity,
 * no unreviewed candidate hotspots, no internal notes. That is enforced server-side (the worker
 * endpoints simply never return those fields), so there is no client-side filter here that could
 * be bypassed or get out of step.
 *
 * Neither the camera nor the location is allowed to block a report. Both are requested only on an
 * explicit press, both have a working fallback, and the submit button stays live through every
 * failure either of them can produce.
 */
import { AlertTriangle, Camera, Crosshair, FileText, Loader2, MapPin, Send, ShieldAlert } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { LivePhotoCapture, type CapturedPhoto } from '../components/safety/LivePhotoCapture';
import { LocationPicker, type LocationPickerValue } from '../components/safety/LocationPicker';
import { PlaceSearch } from '../components/safety/PlaceSearch';
import { useIndiaCheck } from '../hooks/useIndiaCheck';
import { RouteLegend, RoutePanel, type Destination } from '../components/safety/RoutePanel';
import { SafetyMap, type MapMarker } from '../components/safety/SafetyMap';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { Chip } from '../components/ui/primitives';
import { RiskBadge } from '../components/ui/RiskBadge';
import { useSettings } from '../context/SettingsContext';
import { useGeolocation } from '../hooks/useGeolocation';
import { toDisplayRisk, type PublicAlert, type RouteResponse, type WorkerSubmission } from '../types/safety';

/** Fallback view when nothing is located yet. Bengaluru — the project's existing demo locale. */
const DEFAULT_CENTER: [number, number] = [12.9716, 77.5946];

// --- Report -------------------------------------------------------------------------------------

const EMPLOYEE_STORAGE_KEY = 'eco_worker_employee_id';

function getRememberedEmployeeId(): string {
  try {
    return window.localStorage.getItem(EMPLOYEE_STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
}

export function WorkerReportPage() {
  const { api } = useSettings();
  const [employeeId, setEmployeeId] = useState(getRememberedEmployeeId);
  const [text, setText] = useState('');
  const [location, setLocation] = useState<LocationPickerValue>({ fix: null, confirmed: false });
  const [photo, setPhoto] = useState<CapturedPhoto | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [photoWarning, setPhotoWarning] = useState<string | null>(null);
  const [result, setResult] = useState<WorkerSubmission | null>(null);

  const submit = async () => {
    const body = text.trim();
    if (!body) {
      setError('Describe what you saw before submitting.');
      return;
    }
    setBusy(true);
    setError(null);
    setPhotoWarning(null);
    setResult(null);

    /* Only a CONFIRMED location is sent. An unconfirmed pin is something the worker was still
       looking at, and geotagging a hazard with it would put it somewhere nobody vouched for. */
    const fix = location.confirmed ? location.fix : null;

    try {
      const submitted = await api.submitWorkerReport({
        reportText: body,
        employeeId: employeeId ? employeeId.trim() : undefined,
        latitude: fix?.latitude ?? null,
        longitude: fix?.longitude ?? null,
        // Only a device fix has a measured accuracy; a tap or a search result has none.
        gpsAccuracy: fix?.source === 'browser_gps' ? fix.accuracy : null,
        locationSource: fix?.source ?? 'unknown',
        locationText: fix?.label ?? null,
        locationCapturedAt: fix?.capturedAt ?? null,
      });
      setResult(submitted);

      /* The photo is a second request, so a failed upload costs the photo and not the report.
         The worker is told the report landed either way. */
      if (photo && submitted.reportId) {
        try {
          await api.attachReportPhoto(submitted.reportId, photo.file, photo.capturedAt);
        } catch {
          setPhotoWarning('Your report was submitted, but the photo could not be uploaded.');
        }
      }

      setText('');
      setPhoto(null);
      setLocation({ fix: null, confirmed: false });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not submit the report.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <DashboardCard title="Report a Safety Issue"
                     subtitle="Describe what you saw — your name is never shown to other workers"
                     icon={FileText} iconColor="#2563eb">
        <div className="mb-3 flex items-center gap-2">
          <label htmlFor="worker-employee-id" className="text-xs font-medium text-fg-muted">
            Employee ID:
          </label>
          <input
            id="worker-employee-id"
            value={employeeId}
            onChange={(e) => {
              const val = e.target.value.trim().toUpperCase();
              setEmployeeId(val);
              try { window.localStorage.setItem(EMPLOYEE_STORAGE_KEY, val); } catch { /* optional */ }
            }}
            placeholder="e.g. EMP001"
            className="w-32 rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 font-mono text-xs text-fg outline-none focus:border-brand/40"
          />
          <span className="text-[11px] text-fg-subtle">Reports will be saved to this worker profile</span>
        </div>

        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={5}
          placeholder="e.g. I nearly slipped because of oil on the floor near the loading bay."
          className="w-full resize-y rounded-xl border border-black/[0.08] bg-black/[0.02] px-3.5 py-3 text-sm text-fg outline-none transition placeholder:text-fg-subtle focus:border-brand/40"
        />

        <div className="mt-4">
          <p className="eyebrow mb-1.5 flex items-center gap-1.5"><Camera className="size-3" /> Photo (optional)</p>
          <LivePhotoCapture photo={photo} onChange={setPhoto} />
        </div>

        <div className="mt-4">
          <p className="eyebrow mb-1.5 flex items-center gap-1.5"><MapPin className="size-3" /> Location (optional)</p>
          <LocationPicker value={location} onChange={setLocation} />
        </div>

        <div className="mt-4 flex justify-end">
          <Button variant="primary" icon={busy ? Loader2 : Send} loading={busy} onClick={() => void submit()}>
            Submit Report
          </Button>
        </div>
        {error && (
          <p className="mt-3 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-xs text-risk-high">
            {error}
          </p>
        )}
      </DashboardCard>

      {result && (
        <DashboardCard title="Report submitted" subtitle="Thank you — the safety team has been notified"
                       icon={ShieldAlert} iconColor="#059669"
                       actions={<RiskBadge level={toDisplayRisk(result.analysis.riskLevel)} suffix="RISK" size="md" />}>
          <p className="text-[13px] text-fg-muted">{result.extraction.summary}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {result.extraction.riskFactors.map((factor) => <Chip key={factor}>{factor}</Chip>)}
          </div>
          {photoWarning && (
            <p className="mt-2 rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
              {photoWarning}
            </p>
          )}
          <p className="mt-3 rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2 text-[11px] leading-relaxed text-fg-subtle">
            A safety officer reviews every report. {result.hotspotRule.summary} Alerts appear on your
            Safety Map only after the safety team publishes them.
          </p>
        </DashboardCard>
      )}
    </div>
  );
}

// --- Alerts -------------------------------------------------------------------------------------

function useAlerts() {
  const { api } = useSettings();
  const [alerts, setAlerts] = useState<PublicAlert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setAlerts((await api.workerAlerts()).alerts);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load alerts.');
    }
  }, [api]);
  useEffect(() => { void load(); }, [load]);
  return { alerts, error, reload: load };
}

export function WorkerAlertsPage() {
  const { alerts, error } = useAlerts();
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <DashboardCard title="Safety Alerts" subtitle="Published by the safety team" icon={AlertTriangle} iconColor="#dc2626">
        {error && <p className="text-sm text-risk-high">{error}</p>}
        {!error && alerts.length === 0 && (
          <p className="text-sm text-fg-muted">No active safety alerts. Reports under review are not shown here.</p>
        )}
        <ul className="space-y-2">
          {alerts.map((alert) => (
            <li key={alert.id} className="rounded-lg border border-risk-high/20 bg-risk-high/[0.05] px-3 py-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-semibold text-fg">⚠️ {alert.title}</span>
                <span className="shrink-0 text-[10px] tracking-wider text-fg-subtle uppercase">{alert.severity}</span>
              </div>
              <p className="mt-1 text-[12.5px] leading-relaxed text-fg-muted">{alert.message}</p>
              <p className="mt-1.5 text-[10.5px] text-fg-subtle">
                {alert.locationText ?? 'Location marked on the map'} · Issued by {alert.issuedBy}
              </p>
            </li>
          ))}
        </ul>
      </DashboardCard>
    </div>
  );
}

// --- Worker map -----------------------------------------------------------------------------------

/**
 * The worker's map, now with destination routing.
 *
 * Everything already here is kept: published alerts, Find My Location, the disclaimer that
 * individual reports stay private. Routing is added alongside rather than replacing any of it.
 *
 * The start location follows the stated priority — a live GPS fix first, then whatever the worker
 * last confirmed, then a point they set by hand. A GPS failure narrows the options; it never
 * stops the worker routing.
 */
export function WorkerMapPage() {
  const { alerts, error } = useAlerts();
  const geo = useGeolocation();
  const india = useIndiaCheck();
  const [manualStart, setManualStart] = useState<
    { latitude: number; longitude: number; label?: string } | null>(null);
  const [pickingStart, setPickingStart] = useState(false);
  const [destination, setDestination] = useState<Destination | null>(null);
  const [pickingDestination, setPickingDestination] = useState(false);
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [focusAlert, setFocusAlert] = useState<[number, number] | null>(null);
  const [recenterTo, setRecenterTo] = useState<[number, number] | null>(null);

  /* Start priority: whichever the worker chose most recently wins, because each one is a
     deliberate act and silently preferring an older GPS fix over a place they just searched for
     would leave the map showing one thing and route from another. Choosing a start clears the
     other, so there is never a stale coordinate lying behind the visible one. */
  const startPoint = manualStart ?? (geo.fix
    ? { latitude: geo.fix.latitude, longitude: geo.fix.longitude, label: undefined }
    : null);

  /* Validate GPS fix against India boundaries */
  useEffect(() => {
    if (geo.fix) {
      const currentFix = geo.fix;
      void india.check(currentFix.latitude, currentFix.longitude).then((verdict) => {
        if (!verdict.accepted) {
          geo.clear();
          setManualStart(null);
        } else {
          setRecenterTo([currentFix.latitude, currentFix.longitude]);
          setRoute(null);
        }
      });
    }
  }, [geo.fix]); // eslint-disable-line react-hooks/exhaustive-deps

  /* One route is drawn, because the backend returns one. Colour carries the outcome: blue for an
     ordinary shortest route, green where it was adjusted around an alert, red where nothing found
     was clear — so the map agrees with the panel instead of showing a neutral line either way. */
  const routeLines = route?.found
    ? [{
        id: route.selected ?? 'route',
        positions: route.route.map((point) => [point.latitude, point.longitude] as [number, number]),
        color: route.selected === 'alternative' ? '#059669'
             : route.selected === 'none_clear' ? '#dc2626' : '#2563eb',
        emphasis: true,
      }]
    : [];

  const markers: MapMarker[] = [
    ...alerts
      .filter((alert) => alert.latitude !== null && alert.longitude !== null)
      .map((alert) => ({
        id: alert.id,
        latitude: alert.latitude as number,
        longitude: alert.longitude as number,
        kind: 'published' as const,
        title: `⚠ ${alert.title}`,
        body: `${alert.message}\n\nIssued by ${alert.issuedBy}`,
        radiusMeters: alert.radiusMeters,
      })),
    ...(startPoint ? [{ id: 'start', latitude: startPoint.latitude, longitude: startPoint.longitude,
                        kind: 'start' as const,
                        title: geo.fix ? 'Your location' : 'Start (selected)' }] : []),
    ...(destination ? [{ id: 'destination', latitude: destination.latitude,
                         longitude: destination.longitude, kind: 'destination' as const,
                         title: destination.label ?? 'Destination' }] : []),
  ];

  const center: [number, number] = startPoint
    ? [startPoint.latitude, startPoint.longitude]
    : markers.length ? [markers[0].latitude, markers[0].longitude] : DEFAULT_CENTER;

  /* A tap means different things depending on which control is armed. Only one can be armed at a
     time, so a tap is never ambiguous. */
  const handlePick = (latitude: number, longitude: number) => {
    if (pickingStart) {
      void india.check(latitude, longitude).then((verdict) => {
        if (!verdict.accepted) return;    // rejected points are discarded, never relocated
        setManualStart({ latitude, longitude });
        setPickingStart(false);
        setRecenterTo([latitude, longitude]);
        setRoute(null);
      });
    } else if (pickingDestination) {
      void india.check(latitude, longitude).then((verdict) => {
        if (!verdict.accepted) return;
        setDestination({ latitude, longitude, label: null, source: 'manual_map', confirmed: false });
        setPickingDestination(false);
        setRoute(null);
      });
    }
  };

  const fitBounds = route?.found && route.route.length > 1
    ? route.route.map((point) => [point.latitude, point.longitude] as [number, number])
    : null;

  return (
    <div className="space-y-4">
      <DashboardCard
        title="Safety Map"
        subtitle="Published safety alerts near you"
        icon={MapPin}
        iconColor="#dc2626"
      >
        {error && <p className="mb-2 text-sm text-risk-high">{error}</p>}

        {/* GPS problems are reported here rather than swallowed, and never block routing. */}
        {geo.message && (
          <p role="status" className="mb-2 rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
            {geo.message}
          </p>
        )}
        {pickingStart && (
          <p className="mb-2 rounded-lg border border-info/20 bg-info/[0.06] px-3 py-2 text-xs text-info">
            Tap anywhere on the map to set your start location.
          </p>
        )}

        <div className="mb-3">
          <p className="eyebrow mb-1.5 font-semibold text-fg">CURRENT LOCATION</p>
          <PlaceSearch
            label="Search current location"
            placeholder="Search current location..."
            onChoose={(choice) => {
              setManualStart({ latitude: choice.latitude, longitude: choice.longitude,
                               label: choice.label });
              setPickingStart(false);
              setRecenterTo([choice.latitude, choice.longitude]);
              setRoute(null);   // the old route started somewhere else
            }}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" icon={Crosshair} loading={geo.isLocating}
                    onClick={() => {
                      setPickingStart(false);
                      setManualStart(null);   // a fresh GPS fix supersedes an earlier choice
                      india.clear();
                      geo.locate();
                    }}>
              Find My Location
            </Button>
            <Button size="sm" variant={pickingStart ? 'primary' : 'ghost'} icon={MapPin}
                    onClick={() => { setPickingDestination(false); setPickingStart(!pickingStart); }}>
              {pickingStart ? 'Tap the map…' : 'Select Current Location on Map'}
            </Button>
          </div>
          {india.rejection && (
            <p role="status" className="mt-1.5 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-xs text-risk-high">
              {india.rejection} You can search for a location instead.
            </p>
          )}
          {startPoint && (
            <p className="mt-1.5 text-[11px] text-fg-muted">
              📍 Start: {manualStart?.label ?? (geo.fix ? `Your location (±${Math.round(geo.fix.accuracy)} m)` : 'Selected on map')}
              <span className="ml-1.5 font-mono text-[10px] text-fg-subtle">
                {startPoint.latitude.toFixed(5)}, {startPoint.longitude.toFixed(5)}
              </span>
            </p>
          )}
        </div>

        <div className="mb-3">
          <RoutePanel
            destination={destination}
            onDestinationChange={setDestination}
            pickingDestination={pickingDestination}
            onPickingChange={(next) => { setPickingDestination(next); if (next) setPickingStart(false); }}
            hasStart={Boolean(startPoint)}
            startMessage={geo.message}
            route={route}
            onRouteChange={setRoute}
            startPoint={startPoint}
            onViewAlert={(alert) => setFocusAlert([alert.latitude, alert.longitude])}
          />
        </div>

        <SafetyMap
          markers={markers}
          center={center}
          zoom={14}
          height={440}
          recenterTo={focusAlert ?? recenterTo ?? (geo.fix ? [geo.fix.latitude, geo.fix.longitude] : null)}
          routes={routeLines}
          fitBounds={fitBounds}
          onPick={pickingStart || pickingDestination ? handlePick : undefined}
        />

        <div className="mt-2">
          <RouteLegend />
        </div>
        <p className="mt-2 text-[11px] text-fg-subtle">
          Individual reports are private. Only alerts published by the safety team appear here,
          and only those are used when calculating a safety-aware route.
        </p>
      </DashboardCard>
    </div>
  );
}
