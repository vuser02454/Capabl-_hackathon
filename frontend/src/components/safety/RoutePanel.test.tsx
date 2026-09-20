/**
 * Destination routing, from the worker's side of the screen.
 *
 * The contract worth protecting is that the worker is never routed somewhere different without
 * being told. Routing is conditional on the server: when nothing is in range the panel must say
 * the check ran and passed, and when a route WAS adjusted it must say so and give both distances,
 * so a longer walk always carries a visible reason.
 *
 * The privacy half of that is enforced server-side (candidate hotspots are never sent to a
 * worker), so what is asserted here is the half the UI owns: a failed search does not discard the
 * destination already chosen, and an unroutable area is reported rather than papered over.
 *
 * Nothing here touches the network; `fetch` is stubbed and the real ApiClient is driven through it.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../../context/SettingsContext';
import { RoutePanel, type Destination } from './RoutePanel';
import type { RouteAlert, RouteResponse } from '../../types/safety';

const START = { latitude: 12.9716, longitude: 77.5946 };

const DESTINATION: Destination = {
  latitude: 12.9784, longitude: 77.5960, label: 'Warehouse B, Bengaluru',
  source: 'text_search', confirmed: true,
};

const ALERT: RouteAlert = {
  id: 1, title: 'Oil spill — Loading Bay', severity: 'HIGH',
  latitude: 12.9750, longitude: 77.5953, radiusMeters: 150, locationText: 'Loading Bay',
  closestApproachMeters: 70, safetyRadiusMeters: 100, restricted: false,
};

const line = (n: number) =>
  Array.from({ length: n }, (_v, i) => ({ latitude: 12.97 + i * 0.001, longitude: 77.59 }));

/** A clear shortest route — the ordinary case, where the safety check found nothing in range. */
function routeResult(over: Partial<RouteResponse> = {}): RouteResponse {
  return {
    found: true, selected: 'shortest', adjustedForSafety: false, route: line(5),
    distanceMeters: 990, walkingSeconds: 733, alertsNearRoute: [], blockingAlerts: [],
    alternativesEvaluated: 0, nearestAlertMeters: 450, safetyRadiusMeters: 100,
    explanation: 'Shortest route calculated using Dijkstra.',
    graph: { nodes: 5165, edges: 5936, startSnapMeters: 14, destinationSnapMeters: 4 },
    algorithm: 'Dijkstra over an OpenStreetMap walking graph built in this service',
    note: 'Routes consider published safety alerts only.',
    ...over,
  };
}

/** Route each stubbed request by URL and record what was posted. */
function stubFetch(routes: Record<string, unknown>) {
  const calls: Array<{ url: string; body: Record<string, unknown> | null }> = [];
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    const match = Object.keys(routes).find((path) => url.includes(path));
    return Promise.resolve({
      ok: true, status: 200,
      text: () => Promise.resolve(JSON.stringify(match ? routes[match] : {})),
    } as Response);
  }));
  return calls;
}

/** Render with sensible defaults; `props` overrides anything a given test cares about. */
function renderPanel(props: Partial<Parameters<typeof RoutePanel>[0]> = {}) {
  const onRouteChange = vi.fn();
  const onDestinationChange = vi.fn();
  const onViewAlert = vi.fn();
  render(
    <SettingsProvider>
      <RoutePanel
        destination={null}
        onDestinationChange={onDestinationChange}
        pickingDestination={false}
        onPickingChange={vi.fn()}
        hasStart
        startMessage={null}
        route={null}
        onRouteChange={onRouteChange}
        startPoint={START}
        onViewAlert={onViewAlert}
        {...props}
      />
    </SettingsProvider>,
  );
  return { onRouteChange, onDestinationChange, onViewAlert };
}

const clickButton = (name: RegExp) => fireEvent.click(screen.getByRole('button', { name }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// --- destination search --------------------------------------------------------------------

describe('searching for a destination', () => {
  /* Two matches with the ambiguous one first, exactly as Nominatim orders "Whitefield". The old
     behaviour took matches[0] and silently moved the map to New Hampshire. */
  const WHITEFIELD = {
    query: 'Whitefield', cached: false,
    matches: [
      { displayName: 'Whitefield, Coös County, New Hampshire, United States',
        latitude: 44.37313, longitude: -71.61197,
        category: null, placeType: null, importance: null, isWater: false },
      { displayName: 'Whitefield, Bengaluru, Karnataka, India',
        latitude: 12.96980, longitude: 77.75000,
        category: null, placeType: null, importance: null, isWater: false },
    ],
  };

  it('shows the matches instead of adopting one', async () => {
    stubFetch({ '/api/location/search': WHITEFIELD });
    const { onDestinationChange } = renderPanel();

    fireEvent.change(screen.getByLabelText('Search destination'), { target: { value: 'Whitefield' } });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));

    await waitFor(() => expect(screen.getByText(/Whitefield, Bengaluru/)).toBeTruthy());
    expect(screen.getByText(/New Hampshire/)).toBeTruthy();
    expect(onDestinationChange).not.toHaveBeenCalled();
  });

  it('sets the destination to the match the worker picks', async () => {
    stubFetch({ '/api/location/search': WHITEFIELD });
    const { onDestinationChange, onRouteChange } = renderPanel();

    fireEvent.change(screen.getByLabelText('Search destination'), { target: { value: 'Whitefield' } });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));
    await waitFor(() => expect(screen.getByText(/Whitefield, Bengaluru/)).toBeTruthy());
    fireEvent.click(screen.getByText(/Whitefield, Bengaluru/));

    expect(onDestinationChange).toHaveBeenCalledWith(expect.objectContaining({
      latitude: 12.96980, longitude: 77.75000, source: 'text_search', confirmed: true,
    }));
    // A new destination invalidates the route calculated for the old one.
    expect(onRouteChange).toHaveBeenCalledWith(null);
  });

  it('keeps the existing destination when the search finds nothing', async () => {
    stubFetch({ '/api/location/search': { query: 'zzzz', matches: [], cached: false } });
    const { onDestinationChange } = renderPanel({ destination: DESTINATION });

    fireEvent.change(screen.getByLabelText('Search destination'), { target: { value: 'zzzz' } });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));

    await waitFor(() => expect(screen.getByText(/no locations found/i)).toBeTruthy());
    expect(onDestinationChange).not.toHaveBeenCalled();
    expect(screen.getByText(/Warehouse B, Bengaluru/)).toBeTruthy();
  });

  it('points at manual selection when the geocoder is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    renderPanel();

    fireEvent.change(screen.getByLabelText('Search destination'), { target: { value: 'Main Gate' } });
    fireEvent.click(screen.getByRole('button', { name: /^search$/i }));

    await waitFor(() => expect(screen.getByText(/location search is unavailable/i)).toBeTruthy());
  });
});

// --- manual destination ---------------------------------------------------------------------

describe('choosing a destination on the map', () => {
  it('explains what to do once the control is armed', () => {
    renderPanel({ pickingDestination: true });
    expect(screen.getByText(/tap anywhere on the map to choose a destination/i)).toBeTruthy();
  });

  it('shows the tapped coordinates and asks for confirmation before routing', () => {
    renderPanel({
      destination: { latitude: 12.9784, longitude: 77.5960, label: null,
                     source: 'manual_map', confirmed: false },
    });
    expect(screen.getByText(/12\.978400, 77\.596000/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /confirm destination/i })).toBeTruthy();
    // Routing is not offered until the worker has confirmed where they mean.
    expect(screen.queryByRole('button', { name: /calculate route/i })).toBeNull();
  });

  it('offers routing once the destination is confirmed', () => {
    renderPanel({ destination: { ...DESTINATION, source: 'manual_map' } });
    expect(screen.getByRole('button', { name: /calculate route/i })).toBeTruthy();
  });
});

// --- start location --------------------------------------------------------------------------

describe('when there is no start location', () => {
  it('says so and disables routing without hiding the button', () => {
    renderPanel({ destination: DESTINATION, hasStart: false,
                  startMessage: 'Location permission was denied.' });

    expect(screen.getByText(/location permission was denied/i)).toBeTruthy();
    expect(screen.getByText(/set start on map/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /calculate route/i }).hasAttribute('disabled')).toBe(true);
  });
});

// --- calculating ------------------------------------------------------------------------------

describe('calculating a route', () => {
  it('sends only the two endpoints — the safety decision belongs to the backend', async () => {
    const calls = stubFetch({ '/api/worker/route': routeResult() });
    renderPanel({ destination: DESTINATION });

    clickButton(/calculate route/i);

    await waitFor(() => expect(calls.some((c) => c.url.includes('/api/worker/route'))).toBe(true));
    const body = calls.find((c) => c.url.includes('/api/worker/route'))?.body;
    expect(body?.start).toEqual(START);
    expect(body?.destination).toEqual({ latitude: 12.9784, longitude: 77.5960 });
    // No mode and no "compare": asking for an alternative up front is exactly what the
    // conditional rule forbids. The client never requests one.
    expect(body).not.toHaveProperty('mode');
    expect(body).not.toHaveProperty('compare');
  });

  it("surfaces the backend's own explanation when map data is unavailable", async () => {
    // Shaped like a real 503 from the API, so what is asserted is the message a worker sees.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 503,
      text: () => Promise.resolve(JSON.stringify({
        error: { code: 'SERVICE_UNAVAILABLE', message: 'Map data is unavailable right now.' },
      })),
    } as Response));
    const { onRouteChange } = renderPanel({ destination: DESTINATION });

    clickButton(/calculate route/i);

    await waitFor(() => expect(screen.getByText(/map data is unavailable right now/i)).toBeTruthy());
    expect(onRouteChange).toHaveBeenLastCalledWith(null);
  });
});

// --- the three outcomes -------------------------------------------------------------------------

describe('when no published alert is in range', () => {
  const clear = () => renderPanel({ destination: DESTINATION, route: routeResult() });

  it('shows the shortest route distance', () => {
    clear();
    expect(screen.getByText('990 m')).toBeTruthy();
    expect(screen.getByText(/walking distance/i)).toBeTruthy();
  });

  it('says the safety check ran and passed, rather than staying silent', () => {
    clear();
    expect(screen.getByText(/shortest route\. no published safety alert within 100 m/i)).toBeTruthy();
    expect(screen.getByText(/nearest is 450 m away/i)).toBeTruthy();
  });

  it('offers no route options, because nothing was altered', () => {
    clear();
    expect(screen.queryByRole('button', { name: /safety-aware/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /use safety/i })).toBeNull();
    expect(screen.queryByText(/route adjusted for safety/i)).toBeNull();
  });
});

describe('when the shortest route was rejected and an alternative taken', () => {
  const adjusted = () => renderPanel({
    destination: DESTINATION,
    route: routeResult({
      selected: 'alternative', adjustedForSafety: true, distanceMeters: 1120,
      shortestDistanceMeters: 990, blockingAlerts: [ALERT], alternativesEvaluated: 1,
      nearestAlertMeters: 240,
      explanation: 'Shortest route entered a published safety-alert radius. An alternative route was selected.',
    }),
  });

  it('announces that the route was adjusted', () => {
    adjusted();
    expect(screen.getByText(/route adjusted for safety/i)).toBeTruthy();
  });

  it('gives both distances, so the extra walking has a visible reason', () => {
    adjusted();
    expect(screen.getByText('1.12 km')).toBeTruthy();          // the route actually taken
    expect(screen.getByText(/shortest route \(990 m\) entered a published safety-alert area/i)).toBeTruthy();
  });

  it('lets the worker inspect the alert that caused the change', () => {
    const { onViewAlert } = adjusted();
    fireEvent.click(screen.getByRole('button', { name: /view oil spill/i }));
    expect(onViewAlert).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });
});

describe('when no route avoids the alert', () => {
  const unclear = () => renderPanel({
    destination: DESTINATION,
    route: routeResult({
      selected: 'none_clear', adjustedForSafety: false, distanceMeters: 990,
      alertsNearRoute: [ALERT], blockingAlerts: [ALERT], alternativesEvaluated: 3,
      explanation: 'No available route avoids the published safety alert.',
    }),
  });

  it('says so plainly rather than letting a distance read as safe', () => {
    unclear();
    expect(screen.getByText(/no alternative route avoids the published safety alert/i)).toBeTruthy();
    expect(screen.queryByText(/route adjusted for safety/i)).toBeNull();
    // The clear-route reassurance must not appear when nothing is clear.
    expect(screen.queryByText(/no published safety alert within/i)).toBeNull();
  });

  it('reports how many routes were checked', () => {
    unclear();
    expect(screen.getByText(/3 routes were checked/i)).toBeTruthy();
    expect(screen.getByText(/within 100 m of a published alert/i)).toBeTruthy();
  });

  it('still shows the route, because a worker may have to travel anyway', () => {
    unclear();
    expect(screen.getByText('990 m')).toBeTruthy();
  });
});

describe('geometry provenance', () => {
  /* Regression for a real incident: a fabricated straight-line lattice was rendered as
     "Dijkstra over 95 OpenStreetMap nodes". A generated line must never read as map data. */

  it('labels an estimated route as generated, not as OpenStreetMap', () => {
    renderPanel({ destination: DESTINATION, route: routeResult({
      geometrySource: 'estimated',
      estimateWarning: 'OpenStreetMap data could not be loaded, so this is a direct-line estimate. '
                       + 'It does not follow roads or footpaths — check the route yourself before using it.',
      graph: { nodes: 95, edges: 120, startSnapMeters: 0, destinationSnapMeters: 0,
               source: 'estimated' },
    }) });

    expect(screen.getByText(/95 generated points — not map data/i)).toBeTruthy();
    expect(screen.queryByText(/OpenStreetMap nodes/i)).toBeNull();
  });

  it('warns the worker that an estimate does not follow roads', () => {
    renderPanel({ destination: DESTINATION, route: routeResult({
      geometrySource: 'estimated',
      estimateWarning: 'OpenStreetMap data could not be loaded, so this is a direct-line estimate. '
                       + 'It does not follow roads or footpaths — check the route yourself before using it.',
    }) });
    expect(screen.getByText(/does not follow roads or footpaths/i)).toBeTruthy();
  });

  it('does not tick an estimate as a confirmed shortest route', () => {
    renderPanel({ destination: DESTINATION, route: routeResult({ geometrySource: 'estimated' }) });
    // The tick reads as "we checked this against the map", which is exactly what did not happen.
    expect(screen.getByText(/Estimated direct line/i)).toBeTruthy();
    expect(screen.queryByText(/✓ Shortest route/)).toBeNull();
  });

  it('still credits OpenStreetMap when the geometry really came from it', () => {
    renderPanel({ destination: DESTINATION, route: routeResult({
      geometrySource: 'openstreetmap' }) });
    expect(screen.getByText(/5,165 OpenStreetMap nodes/i)).toBeTruthy();
    expect(screen.queryByText(/generated points/i)).toBeNull();
    expect(screen.queryByText(/does not follow roads/i)).toBeNull();
  });
});

describe('attribution and failure', () => {
  it('attributes the path to Dijkstra over an OSM graph', () => {
    renderPanel({ destination: DESTINATION, route: routeResult() });
    expect(screen.getByText(/dijkstra over 5,165 openstreetmap nodes/i)).toBeTruthy();
  });

  it('shows the backend reason when no route could be built at all', () => {
    renderPanel({ destination: DESTINATION, route: routeResult({
      found: false, selected: null, route: [], distanceMeters: null,
      reason: 'Your destination is too far from any mapped path to route to.',
      explanation: 'Your destination is too far from any mapped path to route to.',
    }) });
    expect(screen.getByText(/too far from any mapped path/i)).toBeTruthy();
  });
});
