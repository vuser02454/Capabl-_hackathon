/**
 * Destination routing controls for the Worker Safety Map.
 *
 * The worker picks where they are going, the backend computes the path, and this panel reports
 * what came back. The safety rule is CONDITIONAL and lives on the server: the shortest route is
 * returned unchanged unless it actually enters a published alert's safety radius, and only then
 * is an alternative sought. So there is no route-mode switch here — there is nothing to choose
 * between, and offering a "safety-aware" toggle would imply routes are being altered when in the
 * ordinary case nothing is touched at all.
 *
 * What this panel must do is make the outcome legible. When a route was adjusted it says so and
 * gives both distances; when nothing was in range it says the check ran and passed; when no route
 * is clear it says that plainly rather than showing a distance and letting it read as safe.
 *
 * Only published alerts appear. Candidate hotspots are not sent to workers at all, so there is
 * nothing here to filter — the omission is enforced by the API, not by this component.
 */
import { AlertTriangle, Loader2, MapPin, Navigation, ShieldAlert, X } from 'lucide-react';
import { useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import type { DestinationSource, RouteAlert, RouteResponse } from '../../types/safety';
import { Button } from '../ui/Button';
import { PlaceSearch } from './PlaceSearch';

export interface Destination {
  latitude: number;
  longitude: number;
  label: string | null;
  source: DestinationSource;
  confirmed: boolean;
}

const metres = (value: number | null | undefined) =>
  value == null ? '—' : value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${value} m`;

export function RouteLegend() {
  const items = [
    { swatch: '#2563eb', label: 'Start' },
    { swatch: '#7c3aed', label: 'Destination' },
    { swatch: '#dc2626', label: 'Safety alert' },
    { swatch: '#d97706', label: 'Investigation' },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5 text-[10.5px] text-fg-subtle">
          <span className="size-2 rounded-full" style={{ background: item.swatch }} />
          {item.label}
        </span>
      ))}
      <span className="flex items-center gap-1.5 text-[10.5px] text-fg-subtle">
        <span className="h-[3px] w-5 rounded-full bg-brand" /> Route
      </span>
    </div>
  );
}

export function RoutePanel({
  destination,
  onDestinationChange,
  pickingDestination,
  onPickingChange,
  hasStart,
  startMessage,
  route,
  onRouteChange,
  startPoint,
  onViewAlert,
}: {
  destination: Destination | null;
  onDestinationChange: (next: Destination | null) => void;
  pickingDestination: boolean;
  onPickingChange: (next: boolean) => void;
  hasStart: boolean;
  startMessage: string | null;
  route: RouteResponse | null;
  onRouteChange: (next: RouteResponse | null) => void;
  startPoint: { latitude: number; longitude: number } | null;
  onViewAlert: (alert: RouteAlert) => void;
}) {
  const { api } = useSettings();
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const calculate = async () => {
    if (!startPoint || !destination) return;
    setCalculating(true);
    setError(null);
    try {
      // One request, no mode. The backend decides whether an alternative is even needed.
      onRouteChange(await api.workerRoute({
        start: { latitude: startPoint.latitude, longitude: startPoint.longitude },
        destination: { latitude: destination.latitude, longitude: destination.longitude },
      }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not calculate a route.');
      onRouteChange(null);
    } finally {
      setCalculating(false);
    }
  };

  return (
    <div className="space-y-2.5">
      {/* --- destination ------------------------------------------------------------------ */}
      <div>
        <h3 className="eyebrow mb-0.5 font-semibold text-fg">DESTINATION</h3>
        <p className="text-[11px] text-fg-subtle mb-1.5">Where do you want to go?</p>
        <PlaceSearch
          label="Search destination"
          placeholder="Search destination..."
          onChoose={(choice) => {
            onDestinationChange({
              latitude: choice.latitude, longitude: choice.longitude,
              label: choice.label, source: 'text_search', confirmed: true,
            });
            onPickingChange(false);
            // A new destination invalidates the route that was calculated for the old one.
            onRouteChange(null);
          }}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" variant={pickingDestination ? 'primary' : 'ghost'} icon={MapPin}
                  onClick={() => { onPickingChange(!pickingDestination); setError(null); }}>
            {pickingDestination ? 'Tap the map\u2026' : 'Select Destination on Map'}
          </Button>
          {destination && (
            <Button size="sm" variant="ghost" icon={X}
                    onClick={() => { onDestinationChange(null); onRouteChange(null); }}>
              Clear
            </Button>
          )}
        </div>
      </div>

      {pickingDestination && (
        <p className="rounded-lg border border-info/20 bg-info/[0.06] px-3 py-2 text-xs text-info">
          Tap anywhere on the map to choose a destination.
        </p>
      )}

      {error && (
        <p role="status" className="rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
          {error}
        </p>
      )}

      {/* --- chosen destination + start state -------------------------------------------- */}
      {destination && (
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
          <p className="text-xs text-fg">
            📍 Destination {destination.confirmed ? 'selected' : 'chosen'}
            <span className="text-fg-muted">
              {' · '}{destination.source === 'text_search' ? 'Search result' : 'Selected on map'}
            </span>
          </p>
          {destination.label && <p className="mt-0.5 truncate text-[11px] text-fg-muted">{destination.label}</p>}
          <p className="mt-0.5 font-mono text-[10.5px] text-fg-subtle">
            {destination.latitude.toFixed(6)}, {destination.longitude.toFixed(6)}
          </p>

          {!destination.confirmed && (
            <Button className="mt-2" size="sm" variant="primary"
                    onClick={() => onDestinationChange({ ...destination, confirmed: true })}>
              Confirm Destination
            </Button>
          )}

          {destination.confirmed && (
            <>
              {/* Routing needs a start; say so plainly rather than disabling with no explanation. */}
              {!hasStart && (
                <p className="mt-2 rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-2.5 py-1.5 text-[11.5px] text-risk-moderate">
                  {startMessage ?? 'Current location unavailable.'} Use "Find My Location" or
                  "Set Start on Map" above to choose a starting point.
                </p>
              )}
              <Button className="mt-2" size="sm" variant="primary"
                      icon={calculating ? Loader2 : Navigation}
                      loading={calculating} disabled={!hasStart}
                      onClick={() => void calculate()}>
                Calculate Route
              </Button>
            </>
          )}
        </div>
      )}

      {route && <RouteResult route={route} onViewAlert={onViewAlert} />}
    </div>
  );
}

/**
 * What the routing check found.
 *
 * Three outcomes, each stated as itself rather than blended into one hedge:
 *
 *   shortest    nothing was in range; the plain Dijkstra route is shown, and the clearance is
 *               reported so the worker can see the check ran rather than infer it from silence.
 *   alternative the shortest route was rejected and a clear one took its place. Both distances
 *               are shown, because a longer walk needs a reason the worker can see.
 *   none_clear  every route evaluated was affected. The route is still shown — a worker who has
 *               to get there needs it — but it is never labelled safe.
 */
function RouteResult({
  route, onViewAlert,
}: { route: RouteResponse; onViewAlert: (alert: RouteAlert) => void }) {
  if (!route.found) {
    return (
      <div className="rounded-lg border border-risk-high/25 bg-risk-high/[0.06] px-3 py-2.5">
        <p className="text-xs text-risk-high">{route.reason ?? route.explanation}</p>
      </div>
    );
  }

  const adjusted = route.selected === 'alternative';
  const unclear = route.selected === 'none_clear';
  /* Read from the response, not inferred from a node count: a small real graph is still real. */
  const estimated = (route.geometrySource ?? route.graph.source) === 'estimated';
  const detour =
    route.distanceMeters != null && route.shortestDistanceMeters != null
      ? Math.max(0, Math.round(route.distanceMeters - route.shortestDistanceMeters))
      : 0;
  const pct =
    route.shortestDistanceMeters && route.shortestDistanceMeters > 0
      ? Math.round((detour / route.shortestDistanceMeters) * 100)
      : 0;

  return (
    <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[15px] font-semibold text-fg">{metres(route.distanceMeters)}</span>
        <span className="text-[10.5px] text-fg-subtle">walking distance</span>
      </div>

      {adjusted && (
        <div className="mt-2 rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.08] px-2.5 py-2">
          <p className="flex items-center gap-1.5 text-[12px] font-semibold text-risk-moderate">
            <ShieldAlert className="size-3.5" /> ⚠️ Route adjusted for safety: avoiding published safety alert within {route.safetyRadiusMeters ?? 500} m. Detour: {detour} m (+{pct}%).
          </p>
          <p className="mt-1 text-[11.5px] leading-relaxed text-fg-muted">
            The shortest route ({metres(route.shortestDistanceMeters)}) entered a published
            safety-alert area. This route avoids it.
          </p>
          {route.blockingAlerts.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {route.blockingAlerts.map((alert) => (
                <Button key={alert.id} size="sm" variant="ghost" onClick={() => onViewAlert(alert)}>
                  View {alert.title}
                </Button>
              ))}
            </div>
          )}
        </div>
      )}

      {unclear && (
        <div className="mt-2 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-2.5 py-2">
          <p className="flex items-center gap-1.5 text-[12px] font-semibold text-risk-high">
            <AlertTriangle className="size-3.5" /> ⚠️ No alternative route avoids the published safety alert. Displaying shortest route with safety caution.
          </p>
          <p className="mt-1 text-[11.5px] leading-relaxed text-fg-muted">
            {route.alternativesEvaluated} route{route.alternativesEvaluated === 1 ? ' was' : 's were'}{' '}
            checked and each one passes within {route.safetyRadiusMeters} m of a published alert.
            This route is shown so you can plan, but it is not clear of the alert.
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {route.blockingAlerts.map((alert) => (
              <Button key={alert.id} size="sm" variant="ghost" onClick={() => onViewAlert(alert)}>
                View {alert.title}
              </Button>
            ))}
          </div>
        </div>
      )}

      {route.selected === 'shortest' && (
        <p className="mt-1.5 text-[11.5px] text-fg-muted">
          {estimated ? 'Estimated direct line.' : '✓ Shortest route.'} No published safety alert
          within {route.safetyRadiusMeters ?? 500} m
          {typeof route.nearestAlertMeters === 'number' &&
            ` · nearest is ${route.nearestAlertMeters} m away`}
          .
        </p>
      )}

      {/* An estimated line is not a route over roads and must never be shown as one. The warning
          comes before the distance, so the figure is read in the right light. */}
      {estimated && (
        <p className="mt-2 rounded-lg border border-risk-moderate/30 bg-risk-moderate/[0.09] px-2.5 py-2 text-[11.5px] leading-relaxed text-risk-moderate">
          <AlertTriangle className="mr-1 inline size-3.5" />
          {route.estimateWarning
            ?? 'OpenStreetMap data could not be loaded, so this is a direct-line estimate. It does not follow roads or footpaths — check the route yourself before using it.'}
        </p>
      )}

      <p className="mt-2 font-mono text-[10px] text-fg-subtle">
        {estimated
          ? `Direct-line estimate over ${route.graph.nodes.toLocaleString()} generated points — not map data`
          : `Dijkstra over ${route.graph.nodes.toLocaleString()} OpenStreetMap nodes`}
        {route.graph.startSnapMeters > 30 &&
          ` · ${route.graph.startSnapMeters} m from your start to the nearest path`}
      </p>
    </div>
  );
}
