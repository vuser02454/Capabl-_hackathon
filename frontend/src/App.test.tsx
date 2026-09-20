/**
 * The application mounts, and every page reachable from the role selector renders.
 *
 * This exists because a provider-ordering mistake produces a runtime error that no unit test and
 * no typecheck will catch — each page passes in isolation while the real tree throws on load. A
 * stale HMR module made exactly that error appear in the dev log, and the only way to tell a real
 * ordering bug from an HMR artifact is to mount the genuine <App/> from a cold start, which is
 * what this does.
 *
 * Network access is stubbed rather than mocked away, so the pages take their real data paths.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

/** Leaflet needs layout and canvas APIs jsdom does not provide; the map is not what is under test. */
vi.mock('./components/safety/SafetyMap', () => ({
  SafetyMap: () => <div data-testid="safety-map" />,
}));

/** Every endpoint answers with an empty-but-valid shape, so pages render their empty states. */
const EMPTY: Record<string, unknown> = {
  alerts: [], count: 0, reports: [], hotspots: [], announcements: [], actions: [],
  feedback: [], available: [], matches: [], domainBreakdown: [], hotspotsByStatus: {},
  riskBreakdown: { HIGH: 0, MEDIUM: 0, LOW: 0 },
  reportCount: 0, geolocatedCount: 0, photoCount: 0, hotspotCount: 0, pendingReview: 0,
  publishedAlertCount: 0, recordedActionCount: 0, domains: [],
  rule: { minReports: 3, radiusMeters: 1000, summary: '3+ related reports within a 1 km radius.',
          disclaimer: 'Application/demo threshold, not a regulatory standard.' },
  syntheticNotice: '', disclaimer: '', note: '',
};

beforeEach(() => {
  /* jsdom implements no media queries, and the landing page's responsive layout asks for them.
     Answering "no match" gives the desktop branch, which is enough to prove the tree mounts. */
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  }));
  /* The landing animation observes element size and decodes scene images. jsdom has neither;
     both are stubbed so the tree can mount. Neither is what this file is testing. */
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  if (!HTMLImageElement.prototype.decode) {
    HTMLImageElement.prototype.decode = () => Promise.resolve();
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(EMPTY)),
  } as Response));
  window.location.hash = '';
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Point the hash router at a route and mount the real application. */
function open(hash: string) {
  window.location.hash = hash;
  return render(<App />);
}

describe('the application tree', () => {
  it('mounts the landing page without a provider error', () => {
    // The failure this guards against is a throw during render, not a missing element.
    expect(() => open('')).not.toThrow();
  });

  it('offers both roles on the landing page', () => {
    open('');
    expect(screen.getByRole('button', { name: /worker/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /safety admin/i })).toBeTruthy();
  });
});

describe('every role destination renders', () => {
  const routes: Array<[string, RegExp]> = [
    ['#/worker/report', /report a safety issue/i],
    ['#/worker/map', /where do you want to go\?/i],
    ['#/worker/alerts', /safety alerts/i],
    ['#/admin/dashboard', /safety overview/i],
    ['#/admin/map', /safety map/i],
    ['#/admin/reports', /reports/i],
    ['#/admin/hotspots', /candidate hotspots/i],
    ['#/admin/announcements', /published alerts/i],
  ];

  it.each(routes)('%s', async (hash, heading) => {
    open(hash);
    await waitFor(() => expect(screen.getAllByText(heading).length).toBeGreaterThan(0));
  });
});

describe('the worker map', () => {
  it('keeps its existing controls alongside the new routing ones', async () => {
    open('#/worker/map');
    await waitFor(() => expect(screen.getByLabelText('Search destination')).toBeTruthy());
    // Existing behaviour that must survive the routing addition.
    expect(screen.getByRole('button', { name: /find my location/i })).toBeTruthy();
    expect(screen.getByText(/individual reports are private/i)).toBeTruthy();
    // New routing controls.
    expect(screen.getByRole('button', { name: /select destination on map/i })).toBeTruthy();
    // §18 groups the three current-location controls together; the old duplicate header
    // button was removed rather than kept alongside its twin.
    expect(screen.getByRole('button', { name: /select current location on map/i })).toBeTruthy();
  });

  it('shows the route legend', async () => {
    open('#/worker/map');
    await waitFor(() => expect(screen.getByText('Destination')).toBeTruthy());
    expect(screen.getByText('Start')).toBeTruthy();
    expect(screen.getByText('Route')).toBeTruthy();
  });
});
