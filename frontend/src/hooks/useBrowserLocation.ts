/**
 * One-shot browser geolocation for the dashboard.
 *
 * Deliberately NOT `watchPosition`. An environmental analysis is a snapshot of a point, not a
 * journey: continuous tracking would cost battery, keep a GPS fix alive for no reason, and
 * invite a stream of re-analyses nobody asked for. `useLiveLocation` still watches, because a
 * contamination report is taken while the reporter is walking around a water body — different
 * job, different hook.
 *
 * Permission-prompt contract:
 *   - The browser prompt is triggered at most once per session automatically (the first time the
 *     dashboard has no location), and thereafter only when the user clicks "Use My Location".
 *   - A denial is remembered for the session, so an automatic attempt never re-prompts. An
 *     explicit click always retries: the user may have changed the permission in the meantime.
 *
 * Every failure resolves to a readable message and a manual-search fallback, never a dead state.
 * Geolocation needs a secure context (https, or localhost in development).
 */
import { useCallback, useRef, useState } from 'react';
import type { GeocodeResult } from '../types/environment';
import type { SelectedLocation } from '../types/agents';

export type BrowserLocationFailure = 'denied' | 'unavailable' | 'timeout' | 'unsupported';

export interface BrowserLocationError {
  kind: BrowserLocationFailure;
  message: string;
}

/** Messages the user actually sees. Each one names the fallback rather than just the problem. */
const MESSAGES: Record<BrowserLocationFailure, string> = {
  denied: 'Location permission was denied. Search for a location manually.',
  unavailable: 'Unable to determine your current location. Search manually instead.',
  timeout: 'Locating timed out. Search for a location manually.',
  unsupported: 'This browser cannot read your location here. Search for a location manually.',
};

export const geolocationSupported = () =>
  typeof navigator !== 'undefined' && typeof navigator.geolocation?.getCurrentPosition === 'function';

function classify(error: GeolocationPositionError): BrowserLocationFailure {
  if (error.code === error.PERMISSION_DENIED) return 'denied';
  if (error.code === error.POSITION_UNAVAILABLE) return 'unavailable';
  if (error.code === error.TIMEOUT) return 'timeout';
  return 'unavailable';
}

/** Reverse geocoding is best-effort: coordinates with no name are still a valid location. */
function nameFor(place: GeocodeResult | null, latitude: number, longitude: number): string {
  const resolved = place?.displayName ?? place?.city ?? null;
  return resolved ?? `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
}

export interface BrowserLocationState {
  locating: boolean;
  error: BrowserLocationError | null;
  /** True once permission has been denied in this session — the caller stops auto-prompting. */
  denied: boolean;
  /** Explicit request ("Use My Location"). Resolves to null on failure; never throws. */
  request: () => Promise<SelectedLocation | null>;
  /** Automatic first attempt. Does nothing if a prompt was already answered with a denial. */
  requestOnce: () => Promise<SelectedLocation | null>;
  clearError: () => void;
}

export interface BrowserLocationOptions {
  /** Coordinates -> place name. Failure is tolerated; the fix is still usable without a name. */
  reverseGeocode: (latitude: number, longitude: number) => Promise<GeocodeResult>;
  timeoutMs?: number;
}

export function useBrowserLocation({
  reverseGeocode,
  timeoutMs = 15000,
}: BrowserLocationOptions): BrowserLocationState {
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState<BrowserLocationError | null>(null);
  const [denied, setDenied] = useState(false);
  // Whether an automatic attempt has already been made, so mounting twice cannot double-prompt.
  const attempted = useRef(false);
  const inFlight = useRef<Promise<SelectedLocation | null> | null>(null);

  const fail = useCallback((kind: BrowserLocationFailure) => {
    setLocating(false);
    setError({ kind, message: MESSAGES[kind] });
    if (kind === 'denied') setDenied(true);
    return null;
  }, []);

  const request = useCallback((): Promise<SelectedLocation | null> => {
    if (inFlight.current) return inFlight.current;
    if (!geolocationSupported()) return Promise.resolve(fail('unsupported'));

    attempted.current = true;
    setError(null);
    setLocating(true);

    const promise = new Promise<SelectedLocation | null>((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const { latitude, longitude, accuracy } = position.coords;
          // Name the point through the backend (which owns the Nominatim call). A failure here
          // downgrades the label, never the fix.
          reverseGeocode(latitude, longitude)
            .then((place) => ({ place, geocoding: place.cached ? ('cached' as const) : ('nominatim' as const) }))
            .catch(() => ({ place: null as GeocodeResult | null, geocoding: 'unresolved' as const }))
            .then(({ place, geocoding }) => {
              setLocating(false);
              setError(null);
              setDenied(false);
              resolve({
                latitude,
                longitude,
                accuracy,
                displayName: nameFor(place, latitude, longitude),
                source: 'browser',
                geocoding,
                city: place?.city ?? null,
                state: place?.state ?? null,
                country: place?.country ?? null,
              });
            });
        },
        (cause) => resolve(fail(classify(cause))),
        { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 60000 },
      );
    }).finally(() => {
      inFlight.current = null;
    });

    inFlight.current = promise;
    return promise;
  }, [fail, reverseGeocode, timeoutMs]);

  const requestOnce = useCallback((): Promise<SelectedLocation | null> => {
    // An attempt already running is the answer — return ITS promise, not null. React StrictMode
    // invokes mount effects twice in development, and answering the second call with null would
    // report "no location" while the real fix was still in flight.
    if (inFlight.current) return inFlight.current;
    // Never re-open the permission dialog on our own initiative. Only an explicit click may.
    if (attempted.current || denied) return Promise.resolve(null);
    if (!geolocationSupported()) {
      attempted.current = true;
      return Promise.resolve(fail('unsupported'));
    }
    return request();
  }, [denied, fail, request]);

  const clearError = useCallback(() => setError(null), []);

  return { locating, error, denied, request, requestOnce, clearError };
}
