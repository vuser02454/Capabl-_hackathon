/**
 * A worker's own route history.
 *
 * The privacy half is enforced server-side, so what is checked here is what the UI owns: it asks
 * only for the id the worker typed, it explains a detour in terms the worker can act on, and it
 * distinguishes "you have no recorded routes" from "route history did not exist yet".
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../context/SettingsContext';
import { MyRoutesPage } from './MyRoutesPage';

const NOTE = 'Recorded only when you request a route. Routes calculated before this feature '
           + 'existed were not recorded and cannot be shown.';

const DETOUR = {
  id: 12, createdAt: '2026-09-20T11:05:00+00:00',
  start: { latitude: 13.0, longitude: 77.69 }, destination: { latitude: 12.99, longitude: 77.75 },
  originalDistanceMeters: 8335, selectedDistanceMeters: 9564,
  detourDistanceMeters: 1229, detourRatio: 1.147,
  routeAdjustedForSafety: true, safeAlternativeFound: true,
  selectedReason: 'Shortest route entered a published safety-alert radius.',
  classification: 'HIGH_HAZARD_DETOUR', classificationLabel: 'Rerouted around a high-severity hazard',
  safetyRadiusMeters: 500, originalRouteGeometry: [], selectedRouteGeometry: [],
  alert: { id: 4, title: 'Accident-prone junction', severity: 'HIGH',
           latitude: 13.0, longitude: 77.72, radiusMeters: 500, minimumDistanceMeters: 0 },
};

function stubFetch(payload: unknown, ok = true) {
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    calls.push(String(input));
    return Promise.resolve({
      ok, status: ok ? 200 : 404, text: () => Promise.resolve(JSON.stringify(payload)),
    } as Response);
  }));
  return calls;
}

const renderPage = () => render(<SettingsProvider><MyRoutesPage /></SettingsProvider>);
const load = (id: string) => {
  fireEvent.change(screen.getByLabelText('Employee ID'), { target: { value: id } });
  fireEvent.click(screen.getByRole('button', { name: /load/i }));
};

beforeEach(() => {
  try { window.localStorage.clear(); } catch { /* optional */ }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('before an id is given', () => {
  it('asks for one and fetches nothing', () => {
    const calls = stubFetch({ routes: [], count: 0, note: NOTE });
    renderPage();
    expect(screen.getByText(/enter your employee id/i)).toBeTruthy();
    expect(calls).toEqual([]);
  });
});

describe('loading', () => {
  it('requests only the id that was typed', async () => {
    const calls = stubFetch({ routes: [DETOUR], count: 1, note: NOTE });
    renderPage();
    load('EMP007');
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls[0]).toContain('/api/worker/routes?employee_id=EMP007');
  });

  it('explains a detour in terms the worker can act on', async () => {
    stubFetch({ routes: [DETOUR], count: 1, note: NOTE });
    renderPage();
    load('EMP007');

    await waitFor(() => expect(screen.getByText(/route adjusted for safety/i)).toBeTruthy());
    expect(screen.getByText(/entered a published safety-alert area/i)).toBeTruthy();
    expect(screen.getByText(/1\.23 km longer/)).toBeTruthy();
    expect(screen.getByText(/Accident-prone junction/)).toBeTruthy();
  });

  it('distinguishes an empty history from a missing feature', async () => {
    stubFetch({ routes: [], count: 0, note: NOTE });
    renderPage();
    load('EMP001');

    await waitFor(() => expect(screen.getByText(/no recorded route event exists for you yet/i)).toBeTruthy());
    // The reason an empty list may be empty is stated, not left to be assumed.
    expect(screen.getByText(/were not recorded and cannot be shown/i)).toBeTruthy();
  });

  it('surfaces the backend message for an unknown id', async () => {
    stubFetch({ error: { code: 'NOT_FOUND', message: "No worker with employee id 'NOPE'." } }, false);
    renderPage();
    load('NOPE');
    await waitFor(() => expect(screen.getByText(/no worker with employee id/i)).toBeTruthy());
  });
});
