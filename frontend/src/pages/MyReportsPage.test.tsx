/**
 * The worker's own report history.
 *
 * The boundary this page depends on is enforced server-side, so what is asserted here is the half
 * the UI owns: it requests only the id the worker typed, it renders the history without any
 * review-side field, and it states plainly that the id is not a login. The last one matters —
 * a text box that looks like sign-in but is not would be a misleading security signal.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../context/SettingsContext';
import { MyReportsPage } from './MyReportsPage';

vi.mock('../components/safety/SafetyMap', () => ({
  SafetyMap: () => <div data-testid="safety-map" />,
}));

const REPORT = {
  id: 12, reportText: 'Oil leaked from a forklift near the loading bay.',
  createdAt: '2026-09-18T09:30:00+00:00', location: 'Loading Bay',
  latitude: 12.9746, longitude: 77.5958, gpsAccuracy: 14.2,
  locationSource: 'browser_gps', locationCapturedAt: '2026-09-18T09:29:00+00:00',
  riskLevel: 'MEDIUM', riskScore: 40, summary: 'Oil spill near the loading bay.',
  hazards: ['Oil spill', 'Slip / trip / fall'], status: 'analyzed',
  hasPhoto: true, photoSource: 'live_camera', photoCapturedAt: '2026-09-18T09:29:30+00:00',
  source: 'worker',
};

const WORKER = {
  id: 1, employeeId: 'EMP001', name: 'Worker 001', email: 'worker001@example.com',
  role: 'WORKER', department: 'Warehouse', status: 'ACTIVE', createdAt: '2026-09-01T00:00:00+00:00',
};

function stubFetch(body: unknown, ok = true, status = 200) {
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    calls.push(String(input));
    return Promise.resolve({
      ok, status, text: () => Promise.resolve(JSON.stringify(body)),
    } as Response);
  }));
  return calls;
}

const renderPage = () => render(<SettingsProvider><MyReportsPage /></SettingsProvider>);

beforeEach(() => {
  try { window.localStorage.clear(); } catch { /* optional */ }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('before an employee id is given', () => {
  it('asks for one instead of fetching anything', () => {
    const calls = stubFetch({});
    renderPage();
    expect(screen.getByText(/enter your employee id/i)).toBeTruthy();
    // No id means no request — the page does not guess whose records to show.
    expect(calls).toEqual([]);
  });
});

describe('loading a history', () => {
  it('requests only the id that was typed', async () => {
    const calls = stubFetch({ worker: WORKER, reports: [REPORT], count: 1 });
    renderPage();

    fireEvent.change(screen.getByLabelText('Employee ID'), { target: { value: 'EMP001' } });
    fireEvent.click(screen.getByRole('button', { name: /load/i }));

    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls[0]).toContain('/api/worker/reports?employee_id=EMP001');
  });

  it('shows each report with its date, location, risk and photo indicator', async () => {
    stubFetch({ worker: WORKER, reports: [REPORT], count: 1 });
    renderPage();

    fireEvent.change(screen.getByLabelText('Employee ID'), { target: { value: 'EMP001' } });
    fireEvent.click(screen.getByRole('button', { name: /load/i }));

    await waitFor(() => expect(screen.getByText(/oil leaked from a forklift/i)).toBeTruthy());
    expect(screen.getByText(/SR-12/)).toBeTruthy();
    expect(screen.getByText(/2026-09-18 09:30/)).toBeTruthy();
    expect(screen.getByText(/Loading Bay/)).toBeTruthy();
    expect(screen.getByLabelText('Photo attached')).toBeTruthy();
    expect(screen.getByLabelText('Has a location')).toBeTruthy();
  });

  it('opens one report to show its coordinates and provenance', async () => {
    stubFetch({ worker: WORKER, reports: [REPORT], count: 1 });
    renderPage();

    fireEvent.change(screen.getByLabelText('Employee ID'), { target: { value: 'EMP001' } });
    fireEvent.click(screen.getByRole('button', { name: /load/i }));
    await waitFor(() => expect(screen.getByText(/oil leaked from a forklift/i)).toBeTruthy());
    fireEvent.click(screen.getByText(/oil leaked from a forklift/i));

    expect(screen.getByText('12.97460, 77.59580')).toBeTruthy();
    expect(screen.getByText('Device GPS')).toBeTruthy();
    expect(screen.getByText('±14 m')).toBeTruthy();
    expect(screen.getByTestId('safety-map')).toBeTruthy();
  });

  it('says the history is empty rather than showing nothing at all', async () => {
    stubFetch({ worker: WORKER, reports: [], count: 0 });
    renderPage();

    fireEvent.change(screen.getByLabelText('Employee ID'), { target: { value: 'EMP001' } });
    fireEvent.click(screen.getByRole('button', { name: /load/i }));

    await waitFor(() => expect(screen.getByText(/have not submitted any reports yet/i)).toBeTruthy());
  });

  it('surfaces the backend message for an unknown id', async () => {
    stubFetch({ error: { code: 'NOT_FOUND', message: "No worker with employee id 'NOPE'." } },
              false, 404);
    renderPage();

    fireEvent.change(screen.getByLabelText('Employee ID'), { target: { value: 'NOPE' } });
    fireEvent.click(screen.getByRole('button', { name: /load/i }));

    await waitFor(() => expect(screen.getByText(/no worker with employee id/i)).toBeTruthy());
  });
});

describe('what the page states about itself', () => {
  it('says the employee id is not a login', async () => {
    stubFetch({ worker: WORKER, reports: [REPORT], count: 1 });
    renderPage();

    fireEvent.change(screen.getByLabelText('Employee ID'), { target: { value: 'EMP001' } });
    fireEvent.click(screen.getByRole('button', { name: /load/i }));

    await waitFor(() => expect(screen.getByText(/this demo has no login/i)).toBeTruthy());
    expect(screen.getByText(/is not a sign-in/i)).toBeTruthy();
    expect(screen.getByText(/you can only see your own\s+reports/i)).toBeTruthy();
  });

  it('renders no review-side field, because the API never sends one', async () => {
    const { container } = render(
      <SettingsProvider><MyReportsPage /></SettingsProvider>,
    );
    stubFetch({ worker: WORKER, reports: [REPORT], count: 1 });

    fireEvent.change(screen.getByLabelText('Employee ID'), { target: { value: 'EMP001' } });
    fireEvent.click(screen.getByRole('button', { name: /load/i }));
    await waitFor(() => expect(screen.getByText(/oil leaked from a forklift/i)).toBeTruthy());
    fireEvent.click(screen.getByText(/oil leaked from a forklift/i));

    /* Scoped to the report list, not the page: the closing disclaimer deliberately mentions
       "internal review notes" in order to say they are never sent, and a page-wide search would
       match that sentence and hide a genuine leak. */
    const list = container.querySelector('ul');
    const text = list?.textContent ?? '';
    for (const term of ['review note', 'reviewed by', 'hotspot', 'supporting report', 'reasoning']) {
      expect(text.toLowerCase()).not.toContain(term);
    }
    // The report itself is present, so an empty list is not passing this by accident.
    expect(text).toContain('Oil leaked from a forklift');
  });
});
