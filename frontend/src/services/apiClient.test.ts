/**
 * The browser->backend boundary for location and environmental data.
 *
 * The architectural rule under test: the browser talks only to FastAPI, and FastAPI talks to
 * OpenAQ, Nominatim and Overpass. Centralising provider calls is what makes throttling, caching
 * and failure handling possible at all — and it is the only way an OpenAQ credential can stay
 * out of a bundle that every visitor downloads.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from './apiClient';
import type { SelectedLocation } from '../types/agents';

const BROWSER_FIX: SelectedLocation = {
  latitude: 12.97162345,
  longitude: 77.59461234,
  accuracy: 18,
  displayName: 'Bengaluru, Karnataka, India',
  source: 'browser',
  geocoding: 'nominatim',
  city: 'Bengaluru',
  state: 'Karnataka',
  country: 'India',
};

/** Capture what the client sends, without any network. */
function stubFetch(payload: unknown = {}) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(payload)),
  } as Response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const sentBody = (fetchMock: ReturnType<typeof stubFetch>, call = 0) =>
  JSON.parse((fetchMock.mock.calls[call][1] as RequestInit).body as string);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('analysis request', () => {
  it('sends the chosen coordinates, preserving full precision', async () => {
    // The UI rounds for display only — the analysis needs the precision to pick the right station.
    const fetchMock = stubFetch();
    await new ApiClient('').analyze('Bengaluru', BROWSER_FIX);

    const body = sentBody(fetchMock);
    expect(body.locationContext.latitude).toBe(12.97162345);
    expect(body.locationContext.longitude).toBe(77.59461234);
    expect(body.locationContext.accuracyM).toBe(18);
    expect(body.demoMode).toBe(false);
  });

  it('preserves the existing location-name contract when no point was picked', async () => {
    const fetchMock = stubFetch();
    await new ApiClient('').analyze('Bengaluru', null);

    const body = sentBody(fetchMock);
    expect(body).toEqual({ location: 'Bengaluru', demoMode: false });
    expect(body.locationContext).toBeUndefined();
  });

  it('marks a searched place as a real coordinate, not a preset', async () => {
    const fetchMock = stubFetch();
    await new ApiClient('').analyze('ignored', { ...BROWSER_FIX, source: 'manual' });

    expect(sentBody(fetchMock).locationContext.source).toBe('browser_geolocation');
  });

  it('marks a preset as a preset', async () => {
    const fetchMock = stubFetch();
    await new ApiClient('').analyze('Bengaluru', {
      ...BROWSER_FIX,
      source: 'preset',
      geocoding: 'preset',
    });

    expect(sentBody(fetchMock).locationContext.source).toBe('preset');
  });

  it('posts to the backend analysis endpoint', async () => {
    const fetchMock = stubFetch();
    await new ApiClient('http://127.0.0.1:8000').analyze('Bengaluru', BROWSER_FIX);
    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/analyze');
  });
});

describe('every provider call goes through the backend', () => {
  it.each([
    ['reverseGeocode', (api: ApiClient) => api.reverseGeocode(12.97, 77.59), '/api/location/reverse'],
    ['searchPlaces', (api: ApiClient) => api.searchPlaces('Bengaluru'), '/api/location/search'],
    ['geographicContext', (api: ApiClient) => api.geographicContext(12.97, 77.59), '/api/location/context'],
    ['nearbyWaterBodies', (api: ApiClient) => api.nearbyWaterBodies(12.97, 77.59), '/api/water/nearby-bodies'],
  ])('%s calls %s, never the provider directly', async (_name, call, path) => {
    const fetchMock = stubFetch({ matches: [], bodies: [] });
    await call(new ApiClient(''));

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toBe(path);
    expect(url).not.toMatch(/nominatim|overpass|openaq/i);
  });

  it('sends coordinates in a POST body, so they never reach an access log', async () => {
    const fetchMock = stubFetch();
    await new ApiClient('').reverseGeocode(12.9716, 77.5946);

    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('12.9716');
    expect(sentBody(fetchMock)).toEqual({ latitude: 12.9716, longitude: 77.5946 });
  });
});

describe('no provider credential can reach the browser', () => {
  // vitest runs from the frontend package root; `import.meta.url` is not a file URL under jsdom.
  const srcDir = resolve(process.cwd(), 'src');

  /** Every shipped source file — test files are excluded, since they name the patterns. */
  function sourceFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((entry: string) => {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) return sourceFiles(full);
      return /\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [full] : [];
    });
  }

  it('never READS a provider credential from the client environment', () => {
    // A VITE_-prefixed variable is inlined into the bundle every visitor downloads, so reading
    // one is what leaks. Naming `OPENAQ_API_KEY` in help text is fine — the credential itself
    // belongs to FastAPI alone (backend/config.py).
    const offenders = sourceFiles(srcDir).filter((file) =>
      /import\.meta\.env\.VITE_[A-Z0-9_]*(KEY|TOKEN|SECRET|OPENAQ|PASSWORD)/i.test(readFileSync(file, 'utf8')),
    );
    expect(offenders).toEqual([]);
  });

  it('never calls a provider host directly from the browser', () => {
    const offenders = sourceFiles(srcDir).filter((file) =>
      /https?:\/\/[^'"`\s]*(api\.openaq\.org|nominatim\.openstreetmap\.org|overpass-api\.de)/i.test(
        readFileSync(file, 'utf8'),
      ),
    );
    expect(offenders).toEqual([]);
  });
});
