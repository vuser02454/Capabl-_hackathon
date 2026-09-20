/**
 * The worker surface's two load-bearing contracts.
 *
 * 1. Location never blocks a report. A worker who declines the permission prompt, or whose device
 *    cannot get a fix, must still be able to file — an unreportable hazard is worse than an
 *    unlocated one. So the submit path has to work with no coordinates at all, and a fix that was
 *    obtained but not confirmed must not be sent.
 * 2. A worker sees published alerts and nothing else. That is enforced server-side (the worker
 *    endpoints simply never return raw reports), and the tests here check the consequence the user
 *    can actually see: the alerts list says what it is showing, and says what it is not.
 *
 * Nothing here touches the network. `fetch` is stubbed and the component is driven through the
 * real `ApiClient`, so the request bodies asserted below are the ones the backend would receive.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '../context/SettingsContext';
import { WorkerAlertsPage, WorkerReportPage } from './WorkerPages';

/** Leaflet needs a real layout box and a canvas; neither exists in jsdom. The map is not what
 *  these tests are about, so it is replaced by a marker-count probe. */
vi.mock('../components/safety/SafetyMap', () => ({
  SafetyMap: ({ markers }: { markers: Array<{ id: string | number }> }) => (
    <div data-testid="safety-map" data-markers={markers.length} />
  ),
}));

const ANALYSIS = {
  reportId: 42,
  extraction: { summary: 'Oil on the floor near the loading bay.', riskFactors: ['Oil spill'] },
  analysis: { riskLevel: 'MEDIUM', riskScore: 40 },
  hotspotRule: { minReports: 3, radiusMeters: 1000,
                 summary: 'Candidate hotspot: 3+ related reports within a 1 km radius.',
                 disclaimer: 'Application/demo threshold, not a regulatory standard.' },
};

const PUBLISHED_ALERT = {
  id: 1,
  title: 'Safety Alert — Loading Bay',
  message: 'Oil spill / slip hazard has been reported in this area.',
  severity: 'MEDIUM',
  latitude: 12.9718,
  longitude: 77.5945,
  radiusMeters: 1000,
  locationText: 'Loading Bay',
  publishedAt: '2026-09-20T05:51:15Z',
  issuedBy: 'Safety Team',
};

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

const renderPage = (page: React.ReactNode) => render(<SettingsProvider>{page}</SettingsProvider>);

const describeWhat = (text: string) => {
  fireEvent.change(screen.getByPlaceholderText(/e\.g\. I nearly slipped/i), { target: { value: text } });
};

const clickButton = (name: RegExp) => fireEvent.click(screen.getByRole('button', { name }));

/** The body of the POST to /api/worker/reports, or undefined if none was made. */
const submittedReport = (calls: Array<{ url: string; body: Record<string, unknown> | null }>) =>
  calls.find((call) => call.url.includes('/api/worker/reports'))?.body;

beforeEach(() => {
  Object.defineProperty(navigator, 'geolocation', { value: undefined, configurable: true, writable: true });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('filing a report without a location', () => {
  it('submits, and tells the backend the location is unknown rather than guessing one', async () => {
    const calls = stubFetch({ '/api/worker/reports': ANALYSIS });
    renderPage(<WorkerReportPage />);

    describeWhat('Oil spill near the loading bay.');
    clickButton(/submit report/i);

    await waitFor(() => expect(submittedReport(calls)).toBeTruthy());
    expect(submittedReport(calls)).toEqual({
      report_text: 'Oil spill near the loading bay.',
      latitude: null,
      longitude: null,
      gps_accuracy: null,
      location_source: 'unknown',
      location_text: null,
      location_captured_at: null,
    });
  });

  it('says so up front, so nobody waits for a permission prompt before reporting', () => {
    stubFetch({});
    renderPage(<WorkerReportPage />);
    expect(screen.getByText(/location is optional/i)).toBeTruthy();
  });

  it('refuses an empty report rather than sending a blank one', async () => {
    const calls = stubFetch({ '/api/worker/reports': ANALYSIS });
    renderPage(<WorkerReportPage />);

    clickButton(/submit report/i);

    // Full sentence: the card's subtitle also begins "Describe what you saw".
    await waitFor(() => expect(screen.getByText(/describe what you saw before submitting/i)).toBeTruthy());
    expect(submittedReport(calls)).toBeUndefined();
  });
});

describe('when the device cannot be located', () => {
  it('offers manual selection instead of dead-ending the report', async () => {
    stubFetch({});
    renderPage(<WorkerReportPage />);

    // No geolocation API at all — the harshest version of "no fix available".
    clickButton(/find my location/i);

    await waitFor(() => expect(screen.getByText(/select it on the map|select the location on the map/i)).toBeTruthy());
    // The submit button is still live: a failed fix must never disable reporting.
    expect(screen.getByRole('button', { name: /submit report/i }).hasAttribute('disabled')).toBe(false);
  });

  it('sends a manually picked point as manual_map, with no fabricated GPS accuracy', async () => {
    const calls = stubFetch({ '/api/worker/reports': ANALYSIS });
    renderPage(<WorkerReportPage />);

    describeWhat('Nearly slipped on oily flooring.');
    clickButton(/select location on map/i);
    await waitFor(() => expect(screen.getByTestId('safety-map')).toBeTruthy());
    clickButton(/confirm location/i);
    clickButton(/submit report/i);

    await waitFor(() => expect(submittedReport(calls)).toBeTruthy());
    const body = submittedReport(calls);
    expect(body?.location_source).toBe('manual_map');
    // A hand-placed pin has no measured accuracy; reporting one would be an invented number.
    expect(body?.gps_accuracy).toBeNull();
    expect(typeof body?.latitude).toBe('number');
    expect(typeof body?.longitude).toBe('number');
  });

  it('does not send a fix the worker never confirmed', async () => {
    const calls = stubFetch({ '/api/worker/reports': ANALYSIS });
    renderPage(<WorkerReportPage />);

    describeWhat('Blocked fire exit.');
    clickButton(/select location on map/i);
    await waitFor(() => expect(screen.getByTestId('safety-map')).toBeTruthy());
    // Deliberately skip "Confirm Location".
    clickButton(/submit report/i);

    await waitFor(() => expect(submittedReport(calls)).toBeTruthy());
    expect(submittedReport(calls)?.latitude).toBeNull();
    expect(submittedReport(calls)?.location_source).toBe('unknown');
  });
});

describe('the submitted-report acknowledgement', () => {
  it('states that a human reviews it and that alerts appear only once published', async () => {
    stubFetch({ '/api/worker/reports': ANALYSIS });
    renderPage(<WorkerReportPage />);

    describeWhat('Oil spill near the loading bay.');
    clickButton(/submit report/i);

    await waitFor(() => expect(screen.getByText(/report submitted/i)).toBeTruthy());
    expect(screen.getByText(/a safety officer reviews every report/i)).toBeTruthy();
    expect(screen.getByText(/only after the safety team publishes/i)).toBeTruthy();
    // The rule is quoted as the backend stated it, not restated by the UI.
    expect(screen.getByText(/3\+ related reports within a 1 km radius/i)).toBeTruthy();
  });
});

describe('the worker alerts list', () => {
  it('shows a published alert with the team that issued it', async () => {
    stubFetch({ '/api/worker/alerts': { alerts: [PUBLISHED_ALERT], count: 1 } });
    renderPage(<WorkerAlertsPage />);

    await waitFor(() => expect(screen.getByText(/Safety Alert — Loading Bay/)).toBeTruthy());
    expect(screen.getByText(/Oil spill \/ slip hazard has been reported/)).toBeTruthy();
    expect(screen.getByText(/Issued by Safety Team/)).toBeTruthy();
  });

  it('says explicitly that reports under review are not shown, so silence is not read as safety', async () => {
    stubFetch({ '/api/worker/alerts': { alerts: [], count: 0 } });
    renderPage(<WorkerAlertsPage />);

    await waitFor(() => expect(screen.getByText(/no active safety alerts/i)).toBeTruthy());
    expect(screen.getByText(/reports under review are not shown/i)).toBeTruthy();
  });
});
