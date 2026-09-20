/**
 * Worker Route Intelligence.
 *
 * The claim this screen makes is "this worker was rerouted", and the test that matters is that
 * the claim is shown rather than asserted: when a route was adjusted BOTH geometries are drawn,
 * so an admin can see the rejected route beside the one served. A single line would leave them
 * taking the label's word for it.
 *
 * The other one is the coverage note. An empty list must not read as "nobody has travelled" when
 * it actually means "recording started later".
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../context/SettingsContext';
import { WorkerRoutesPage } from './WorkerRoutesPage';

/** The map is replaced by a probe that reports the lines it was asked to draw. */
vi.mock('../components/safety/SafetyMap', () => ({
  SafetyMap: ({ routes = [] }: { routes?: Array<{ id: string; dashed?: boolean }> }) => (
    <div data-testid="safety-map" data-lines={routes.map((r) => r.id).join(',')}
         data-dashed={routes.filter((r) => r.dashed).map((r) => r.id).join(',')} />
  ),
}));

const line = (n: number) =>
  Array.from({ length: n }, (_v, i) => ({ latitude: 12.97 + i * 0.001, longitude: 77.59 }));

const DETOUR = {
  id: 12, createdAt: '2026-09-20T11:05:00+00:00',
  start: { latitude: 13.0075, longitude: 77.6959 },
  destination: { latitude: 12.9957, longitude: 77.7579 },
  originalDistanceMeters: 8335, selectedDistanceMeters: 9564,
  detourDistanceMeters: 1229, detourRatio: 1.147,
  routeAdjustedForSafety: true, safeAlternativeFound: true,
  selectedReason: 'Shortest route entered a published safety-alert radius. An alternative route was selected.',
  classification: 'HIGH_HAZARD_DETOUR', classificationLabel: 'Rerouted around a high-severity hazard',
  safetyRadiusMeters: 500,
  originalRouteGeometry: line(6), selectedRouteGeometry: line(8),
  alert: { id: 4, title: 'Accident-prone junction', severity: 'HIGH',
           latitude: 13.0044, longitude: 77.7282, radiusMeters: 500, minimumDistanceMeters: 0 },
  employeeId: 'EMP007', workerName: 'Worker 007', department: 'Logistics',
};

const NORMAL = {
  ...DETOUR, id: 5, employeeId: 'EMP001', workerName: 'Worker 001',
  routeAdjustedForSafety: false, safeAlternativeFound: null,
  detourDistanceMeters: 0, detourRatio: 1.0,
  classification: 'NORMAL_ROUTE', classificationLabel: 'Normal route',
  selectedDistanceMeters: 8335, alert: null, selectedReason: 'Shortest route calculated using Dijkstra.',
  originalRouteGeometry: line(6), selectedRouteGeometry: line(6),
};

function body(routes: unknown[], over: Record<string, unknown> = {}) {
  return {
    routes, count: routes.length,
    summary: {
      total: routes.length,
      byClassification: [
        { classification: 'NORMAL_ROUTE', label: 'Normal route', count: 1 },
        { classification: 'HIGH_HAZARD_DETOUR', label: 'Rerouted', count: 1 },
      ],
      normal: 1, moderateHazard: 0, highHazardDetour: 1, noSafeAlternative: 0,
      workersAffected: 1, alertsInvolved: 1,
      coverageNote: 'Route events are recorded from the moment a worker requests a route. '
                    + 'No history exists for routes calculated before this was introduced.',
    },
    classifications: [{ id: 'NORMAL_ROUTE', label: 'Normal route' },
                      { id: 'HIGH_HAZARD_DETOUR', label: 'Rerouted' }],
    departments: ['Warehouse', 'Logistics'],
    ...over,
  };
}

function stubFetch(payload: unknown) {
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    calls.push(String(input));
    return Promise.resolve({
      ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(payload)),
    } as Response);
  }));
  return calls;
}

const renderPage = () => render(<SettingsProvider><WorkerRoutesPage /></SettingsProvider>);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the summary', () => {
  it('shows the counts by classification', async () => {
    stubFetch(body([NORMAL, DETOUR]));
    renderPage();
    await waitFor(() => expect(screen.getByText('Route events')).toBeTruthy());
    expect(screen.getByText('High-hazard detours')).toBeTruthy();
    expect(screen.getByText('Workers affected')).toBeTruthy();
  });

  it('states that history begins when recording began', async () => {
    stubFetch(body([NORMAL]));
    renderPage();
    // An empty or short list must not read as "nobody travelled".
    await waitFor(() => expect(screen.getByText(/No history exists for routes calculated before/i)).toBeTruthy());
  });

  it('says so plainly when nothing matches', async () => {
    stubFetch(body([]));
    renderPage();
    await waitFor(() => expect(screen.getByText(/no recorded route event matches/i)).toBeTruthy());
  });
});

describe('opening a detour', () => {
  it('draws BOTH the rejected and the served route', async () => {
    stubFetch(body([DETOUR]));
    renderPage();
    await waitFor(() => expect(screen.getByText(/RE-12/)).toBeTruthy());
    fireEvent.click(screen.getByText(/RE-12/));

    const map = await screen.findByTestId('safety-map');
    // The whole point: an admin can see the route that was rejected, not just be told about it.
    expect(map.getAttribute('data-lines')).toBe('original,selected');
    expect(map.getAttribute('data-dashed')).toBe('original');
  });

  it('shows both distances, the detour and the hazard clearance', async () => {
    stubFetch(body([DETOUR]));
    renderPage();
    await waitFor(() => expect(screen.getByText(/RE-12/)).toBeTruthy());
    fireEvent.click(screen.getByText(/RE-12/));

    expect(screen.getByText('8.34 km')).toBeTruthy();        // original
    expect(screen.getByText('9.56 km')).toBeTruthy();        // selected
    expect(screen.getByText('1.147×')).toBeTruthy();         // detour ratio
    expect(screen.getByText(/Accident-prone junction/)).toBeTruthy();
  });

  it('explains that the geometry is the one recorded at the time', async () => {
    stubFetch(body([DETOUR]));
    renderPage();
    await waitFor(() => expect(screen.getByText(/RE-12/)).toBeTruthy());
    fireEvent.click(screen.getByText(/RE-12/));
    expect(screen.getByText(/not a route recalculated now/i)).toBeTruthy();
  });
});

describe('opening a normal route', () => {
  it('draws only the route that was served', async () => {
    stubFetch(body([NORMAL]));
    renderPage();
    await waitFor(() => expect(screen.getByText(/RE-5/)).toBeTruthy());
    fireEvent.click(screen.getByText(/RE-5/));

    const map = await screen.findByTestId('safety-map');
    // Nothing was rejected, so there is no second line to draw.
    expect(map.getAttribute('data-lines')).toBe('selected');
  });
});

describe('filters', () => {
  it('sends the employee id to the backend', async () => {
    const calls = stubFetch(body([NORMAL]));
    renderPage();
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));

    fireEvent.change(screen.getByLabelText('Filter by employee ID'), { target: { value: 'EMP007' } });
    fireEvent.click(screen.getByRole('button', { name: /apply/i }));

    await waitFor(() => expect(calls.some((c) => c.includes('employee_id=EMP007'))).toBe(true));
  });

  it('offers the classifications the backend reported', async () => {
    stubFetch(body([NORMAL]));
    renderPage();
    await waitFor(() => expect(screen.getByLabelText('Filter by classification')).toBeTruthy());
    expect(screen.getByRole('option', { name: 'Rerouted' })).toBeTruthy();
  });
});
