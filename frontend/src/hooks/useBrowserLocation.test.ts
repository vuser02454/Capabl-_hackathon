/**
 * Browser geolocation -> coordinates -> backend reverse geocoding -> SelectedLocation.
 *
 * The contract that matters most here is the one about permission prompts: a denied user must
 * not be asked again on our initiative, and an explicit click must always be allowed to retry.
 * Nothing here touches a real geolocation device or the network.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useBrowserLocation } from './useBrowserLocation';
import type { GeocodeResult } from '../types/environment';

const PERMISSION_DENIED = 1;
const POSITION_UNAVAILABLE = 2;
const TIMEOUT = 3;

function position(latitude = 12.9716, longitude = 77.5946, accuracy = 18) {
  return { coords: { latitude, longitude, accuracy } } as GeolocationPosition;
}

function geolocationError(code: number) {
  return { code, PERMISSION_DENIED, POSITION_UNAVAILABLE, TIMEOUT } as GeolocationPositionError;
}

/** Install a stub geolocation that answers with `outcome`, and count the prompts it received. */
function stubGeolocation(outcome: { position?: GeolocationPosition; error?: GeolocationPositionError }) {
  const getCurrentPosition = vi.fn((onSuccess: PositionCallback, onError?: PositionErrorCallback) => {
    if (outcome.error) onError?.(outcome.error);
    else onSuccess(outcome.position ?? position());
  });
  Object.defineProperty(navigator, 'geolocation', {
    value: { getCurrentPosition },
    configurable: true,
    writable: true,
  });
  return getCurrentPosition;
}

function removeGeolocation() {
  Object.defineProperty(navigator, 'geolocation', { value: undefined, configurable: true, writable: true });
}

const place = (overrides: Partial<GeocodeResult> = {}): GeocodeResult => ({
  displayName: 'Bengaluru, Karnataka, India',
  city: 'Bengaluru',
  state: 'Karnataka',
  country: 'India',
  postcode: null,
  neighbourhood: null,
  waterFeature: null,
  cached: false,
  ...overrides,
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('successful fix', () => {
  it('turns a position into a named SelectedLocation', async () => {
    stubGeolocation({ position: position(12.9716, 77.5946, 18) });
    const reverseGeocode = vi.fn().mockResolvedValue(place());
    const { result } = renderHook(() => useBrowserLocation({ reverseGeocode }));

    const selected = await act(() => result.current.request());

    expect(selected).toEqual({
      latitude: 12.9716,
      longitude: 77.5946,
      accuracy: 18,
      displayName: 'Bengaluru, Karnataka, India',
      source: 'browser',
      geocoding: 'nominatim',
      city: 'Bengaluru',
      state: 'Karnataka',
      country: 'India',
    });
    expect(reverseGeocode).toHaveBeenCalledWith(12.9716, 77.5946);
  });

  it('marks a cached reverse geocode as such, for the provenance strip', async () => {
    stubGeolocation({ position: position() });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place({ cached: true })) }),
    );

    const selected = await act(() => result.current.request());
    expect(selected?.geocoding).toBe('cached');
  });

  it('keeps the fix when the place name cannot be resolved', async () => {
    // Coordinates are what the analysis needs; a missing name only downgrades the label.
    stubGeolocation({ position: position(1.5, 2.5) });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockRejectedValue(new Error('Nominatim down')) }),
    );

    const selected = await act(() => result.current.request());
    expect(selected).toMatchObject({ latitude: 1.5, longitude: 2.5, geocoding: 'unresolved' });
    expect(selected?.displayName).toBe('1.5000, 2.5000');
  });

  it('reports full coordinate precision, rounding only the fallback label', async () => {
    stubGeolocation({ position: position(12.97162345, 77.59461234) });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    const selected = await act(() => result.current.request());
    expect(selected?.latitude).toBe(12.97162345);
    expect(selected?.longitude).toBe(77.59461234);
  });
});

describe('failure fallbacks', () => {
  it.each([
    [PERMISSION_DENIED, 'denied', 'Location permission was denied. Search for a location manually.'],
    [POSITION_UNAVAILABLE, 'unavailable', 'Unable to determine your current location. Search manually instead.'],
    [TIMEOUT, 'timeout', 'Locating timed out. Search for a location manually.'],
  ])('maps error code %i to a message that names the manual fallback', async (code, kind, message) => {
    stubGeolocation({ error: geolocationError(code) });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    const selected = await act(() => result.current.request());

    expect(selected).toBeNull();
    await waitFor(() => expect(result.current.error).toEqual({ kind, message }));
  });

  it('reports unsupported browsers immediately, without a prompt', async () => {
    removeGeolocation();
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    const selected = await act(() => result.current.request());
    expect(selected).toBeNull();
    await waitFor(() => expect(result.current.error?.kind).toBe('unsupported'));
  });

  it('never leaves `locating` stuck on after a failure', async () => {
    stubGeolocation({ error: geolocationError(TIMEOUT) });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    await act(() => result.current.request());
    await waitFor(() => expect(result.current.locating).toBe(false));
  });
});

describe('permission prompt discipline', () => {
  it('does not re-prompt automatically after a denial', async () => {
    const prompt = stubGeolocation({ error: geolocationError(PERMISSION_DENIED) });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    await act(() => result.current.requestOnce());
    await waitFor(() => expect(result.current.denied).toBe(true));
    await act(() => result.current.requestOnce());
    await act(() => result.current.requestOnce());

    expect(prompt).toHaveBeenCalledTimes(1);
  });

  it('prompts automatically only once, even when the first attempt succeeded', async () => {
    const prompt = stubGeolocation({ position: position() });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    await act(() => result.current.requestOnce());
    await act(() => result.current.requestOnce());

    expect(prompt).toHaveBeenCalledTimes(1);
  });

  it('still retries on an explicit click after a denial', async () => {
    // The user may have changed the browser permission in between; a click must be honoured.
    const prompt = stubGeolocation({ error: geolocationError(PERMISSION_DENIED) });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    await act(() => result.current.requestOnce());
    await act(() => result.current.request());

    expect(prompt).toHaveBeenCalledTimes(2);
  });

  it('collapses concurrent requests into one prompt', async () => {
    const prompt = stubGeolocation({ position: position() });
    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    await act(async () => {
      await Promise.all([result.current.request(), result.current.request()]);
    });

    expect(prompt).toHaveBeenCalledTimes(1);
  });

  it('uses getCurrentPosition, never watchPosition', async () => {
    // An analysis is a snapshot of a point, not a journey: continuous tracking is the wrong tool.
    const watchPosition = vi.fn();
    const getCurrentPosition = vi.fn((onSuccess: PositionCallback) => onSuccess(position()));
    Object.defineProperty(navigator, 'geolocation', {
      value: { getCurrentPosition, watchPosition },
      configurable: true,
      writable: true,
    });

    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );
    await act(() => result.current.request());

    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(watchPosition).not.toHaveBeenCalled();
  });
});

describe('React StrictMode double-invocation', () => {
  it('hands the in-flight fix to a second requestOnce, instead of answering null', async () => {
    // StrictMode invokes mount effects twice in development. The second call must not report
    // "no location" while the first attempt is still resolving — that discarded the real fix and
    // left the app analysing the default preset while the UI showed the browser location.
    let settle: (position: GeolocationPosition) => void = () => {};
    const getCurrentPosition = vi.fn((onSuccess: PositionCallback) => {
      settle = onSuccess;
    });
    Object.defineProperty(navigator, 'geolocation', {
      value: { getCurrentPosition },
      configurable: true,
      writable: true,
    });

    const { result } = renderHook(() =>
      useBrowserLocation({ reverseGeocode: vi.fn().mockResolvedValue(place()) }),
    );

    let first: Promise<unknown>, second: Promise<unknown>;
    await act(async () => {
      first = result.current.requestOnce();
      second = result.current.requestOnce();
      settle(position(12.9716, 77.5946));
      await Promise.resolve();
    });

    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(await second!).toMatchObject({ latitude: 12.9716, source: 'browser' });
    expect(await first!).toEqual(await second!);
  });
});
