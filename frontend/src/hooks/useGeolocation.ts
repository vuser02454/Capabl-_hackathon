/**
 * Browser geolocation, requested only on an explicit click.
 *
 * Nothing here runs on mount. The permission prompt appears when the worker presses "Find My
 * Location" and at no other time — a page that asks for location the moment it loads teaches
 * people to deny it, and the denial then costs us the reports that do have a fix.
 *
 * Every failure mode is reported distinctly, because they need different things from the user:
 *
 *   denied      the browser refused; searching or tapping the map is the way forward
 *   timeout     the device is still looking; retrying often works, especially indoors
 *   unavailable no position could be determined at all (no GPS, no wifi positioning)
 *   insecure    the page is not on HTTPS or localhost, so the API is blocked before it is asked
 *   unsupported the browser exposes no geolocation API
 *
 * `insecure` is the one that used to surface as a bare "Could not get a location fix": Chrome and
 * Safari reject geolocation outright on a plain-HTTP origin, which looks identical to a hardware
 * failure from inside the error callback. It is detected up front instead of being guessed at.
 *
 * A fix is never fabricated. `status === 'ready'` implies a real `fix`, so a caller can show
 * "Location captured" on that alone and it cannot be wrong.
 */
import { useCallback, useRef, useState } from 'react';

export interface Fix {
  latitude: number;
  longitude: number;
  /** Metres, as reported by the device. Displayed so the worker can judge whether to trust it. */
  accuracy: number;
  /** How this fix was obtained. Travels with the report so provenance is never inferred later. */
  source: LocationSource;
  /** Human-readable place, when one is known (search results carry one; GPS does not). */
  label?: string;
  /** ISO timestamp of capture, so a stale fix is visible as one. Every path sets it, so it is
   *  required: an optional timestamp invites callers to treat "no time" as a normal case. */
  capturedAt: string;
}

export type LocationSource = 'browser_gps' | 'manual_map' | 'text_search';

export type GeoStatus =
  | 'idle' | 'locating' | 'ready'
  | 'denied' | 'timeout' | 'unavailable' | 'insecure' | 'unsupported' | 'error';

/** First attempt: ask the device for its best fix.
 *
 * `maximumAge: 30_000` accepts a fix up to half a minute old. The previous value of 0 refused
 * every cached position and forced a cold hardware acquisition on each press — which is what made
 * this time out indoors and on desktops, where there is no GPS radio and CoreLocation has to fall
 * back to wifi positioning. Half a minute is recent enough for a hazard report and removes the
 * commonest cause of failure. */
export const GEO_OPTIONS: PositionOptions = {
  enableHighAccuracy: true,
  timeout: 15_000,
  maximumAge: 30_000,
};

/** Second attempt, used only when the first times out.
 *
 * Drops the high-accuracy requirement, which on most platforms is the difference between waiting
 * on a satellite/wifi scan and reading a coarse network position that is already available. A
 * report located to within a few hundred metres is far better than one with no location at all,
 * and the accuracy is shown to the worker either way so a coarse fix is never mistaken for a
 * precise one. */
export const GEO_FALLBACK_OPTIONS: PositionOptions = {
  enableHighAccuracy: false,
  timeout: 10_000,
  maximumAge: 60_000,
};

const MESSAGES: Record<Exclude<GeoStatus, 'idle' | 'locating' | 'ready'>, string> = {
  denied:
    'Location permission was denied. Search for a location or select it on the map.',
  /* Reached only after BOTH the high-accuracy attempt and the low-accuracy fallback have failed,
     so "taking longer than expected" would be misleading — there is nothing still in flight.
     Timeout and unavailable are worded differently because they call for different next steps:
     a timeout may succeed on retry, a device with no positioning hardware will not. */
  timeout:
    'GPS location timed out. Search for a location or select it on the map.',
  unavailable:
    'Your device could not provide a location. Search for a location or select it on the map.',
  insecure:
    'Location needs a secure connection (https or localhost). Search for your location or ' +
    'select the location on the map instead.',
  unsupported:
    'Geolocation is not supported by this browser. Search for a location or select it on the map.',
  error:
    'Your device could not provide a location. Search for a location or select it on the map.',
};

/** Geolocation is blocked outright on insecure origins, so detect it before prompting. */
function secureEnough(): boolean {
  if (typeof window === 'undefined') return false;
  if (window.isSecureContext) return true;
  const host = window.location.hostname;
  return host === 'localhost' || host === '127.0.0.1' || host === '[::1]' || host === '';
}

export function useGeolocation() {
  const [status, setStatus] = useState<GeoStatus>('idle');
  const [fix, setFix] = useState<Fix | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  /** Guards against a slow first attempt resolving after the worker has started a second. */
  const attempt = useRef(0);

  const fail = useCallback((next: Exclude<GeoStatus, 'idle' | 'locating' | 'ready'>) => {
    setStatus(next);
    setMessage(MESSAGES[next]);
  }, []);

  const locate = useCallback(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      fail('unavailable');
      return;
    }
    if (!secureEnough()) {
      fail('insecure');
      return;
    }

    const current = ++attempt.current;
    setStatus('locating');
    setMessage(null);

    const succeed = (position: GeolocationPosition) => {
      if (current !== attempt.current) return; // superseded by a newer press
      setFix({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
        source: 'browser_gps',
        // The device's own timestamp when it has one, so a cached fix reports its real age.
        capturedAt: new Date(position.timestamp || Date.now()).toISOString(),
      });
      setStatus('ready');
      setMessage(null);
    };

    /* Two attempts, not one. A high-accuracy request is what times out indoors and on desktops
       with no GPS radio; retrying without it usually succeeds straight away from a coarse network
       position. Only a non-denial is retried — a refused permission will not change its mind, and
       asking again would simply prompt the worker twice. */
    navigator.geolocation.getCurrentPosition(
      succeed,
      (error) => {
        if (current !== attempt.current) return;
        // 1 PERMISSION_DENIED, 2 POSITION_UNAVAILABLE, 3 TIMEOUT.
        if (error.code === 1) {
          fail('denied');
          return;
        }
        navigator.geolocation.getCurrentPosition(
          succeed,
          (fallbackError) => {
            if (current !== attempt.current) return;
            if (fallbackError.code === 1) fail('denied');
            else if (fallbackError.code === 2) fail('unavailable');
            else fail('timeout');
          },
          GEO_FALLBACK_OPTIONS,
        );
      },
      GEO_OPTIONS,
    );
  }, [fail]);

  /**
   * Set a manual coordinate fix (e.g. from tests or explicit picker).
   */
  const setManualFix = useCallback(
    (next: { latitude: number; longitude: number; accuracy?: number; source?: LocationSource }) => {
      attempt.current += 1;
      setFix({
        latitude: next.latitude, longitude: next.longitude, accuracy: next.accuracy ?? 0,
        source: next.source ?? 'manual_map', capturedAt: new Date().toISOString(),
      });
      setStatus('ready');
      setMessage(null);
    },
    [],
  );

  /**
   * Adopt a location the worker chose by hand — a map tap or a search result.
   *
   * Kept separate from `locate` so the location hierarchy is explicit at the call site: a GPS fix
   * is only ever replaced by another deliberate act, never by a failed lookup.
   */
  const setChosenFix = useCallback(
    (next: { latitude: number; longitude: number; source: LocationSource; label?: string }) => {
      attempt.current += 1; // cancel any in-flight GPS request so it cannot overwrite this
      setFix({ ...next, accuracy: 0, capturedAt: new Date().toISOString() });
      setStatus('ready');
      setMessage(null);
    },
    [],
  );

  const clear = useCallback(() => {
    attempt.current += 1;
    setFix(null);
    setStatus('idle');
    setMessage(null);
  }, []);

  return {
    status,
    fix,
    message,
    locate,
    clear,
    setManualFix,
    setChosenFix,
    isLocating: status === 'locating',
  };
}
