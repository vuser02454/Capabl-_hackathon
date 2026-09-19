/**
 * Live device location for contamination reports.
 *
 * Wraps navigator.geolocation.watchPosition, reverse-geocodes the fix through the backend so a
 * report carries a place name and not just numbers, and asks Overpass which water body the point
 * is actually next to — reverse geocoding only names water when the fix happens to sit on it,
 * which for a photo taken from a bank it usually does not.
 *
 * Privacy contract:
 *   - Tracking only ever starts when the caller asks (`start()`), never on mount. The browser's
 *     own permission prompt is the second gate.
 *   - The fix lives in React state and is sent nowhere until the user confirms a report.
 *   - `stop()` releases the watch; the hook always releases it on unmount.
 *
 * Geolocation needs a secure context (https, or localhost in development). Every failure mode
 * resolves to a readable `error` rather than a silent dead state, because a report with no
 * location is useless and the user needs to know why.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSettings } from '../context/SettingsContext';
import { isAbortError } from '../services/errors';
import type { ReportLocation } from '../types/agents';
import type { NearbyWaterBody } from '../types/environment';

export interface LiveLocationState {
  location: ReportLocation | null;
  /** Closest named OSM water body, once Overpass has answered. Null while unknown. */
  waterBody: NearbyWaterBody | null;
  /** True while the Overpass lookup is in flight. */
  identifyingWater: boolean;
  tracking: boolean;
  /** True while the first fix is still pending. */
  locating: boolean;
  error: string | null;
  /** True once a reverse geocode has named the place (or definitively failed). */
  resolvingPlace: boolean;
  start: () => void;
  stop: () => void;
}

export const geolocationSupported = () =>
  typeof navigator !== 'undefined' && typeof navigator.geolocation?.watchPosition === 'function';

function describe(error: GeolocationPositionError): string {
  if (error.code === error.PERMISSION_DENIED) {
    return 'Location permission was denied. A report needs a location — allow access in your browser to continue.';
  }
  if (error.code === error.POSITION_UNAVAILABLE) {
    return 'Your device could not determine a position. Move somewhere with a clearer sky view and try again.';
  }
  if (error.code === error.TIMEOUT) {
    return 'Locating timed out. Try again, or move somewhere with better GPS reception.';
  }
  return 'Your location could not be read.';
}

export function useLiveLocation(): LiveLocationState {
  const { api, settings } = useSettings();
  const [location, setLocation] = useState<ReportLocation | null>(null);
  const [tracking, setTracking] = useState(false);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resolvingPlace, setResolvingPlace] = useState(false);
  const [waterBody, setWaterBody] = useState<NearbyWaterBody | null>(null);
  const [identifyingWater, setIdentifyingWater] = useState(false);

  const watchRef = useRef<number | null>(null);
  const geocodeRef = useRef<AbortController | null>(null);
  const overpassRef = useRef<AbortController | null>(null);
  const waterFoundFor = useRef<{ latitude: number; longitude: number } | null>(null);
  // Coordinates the place name was resolved for, so panning a few metres does not re-geocode.
  const geocodedFor = useRef<{ latitude: number; longitude: number } | null>(null);

  const stop = useCallback(() => {
    if (watchRef.current !== null) {
      navigator.geolocation.clearWatch(watchRef.current);
      watchRef.current = null;
    }
    geocodeRef.current?.abort();
    geocodeRef.current = null;
    overpassRef.current?.abort();
    overpassRef.current = null;
    setTracking(false);
    setLocating(false);
    setResolvingPlace(false);
    setIdentifyingWater(false);
  }, []);

  const resolvePlace = useCallback(
    (latitude: number, longitude: number) => {
      // Demo Mode has no backend to ask; the coordinates alone still make a valid report.
      if (settings.demoMode) return;
      const previous = geocodedFor.current;
      if (previous && Math.abs(previous.latitude - latitude) < 0.0005 && Math.abs(previous.longitude - longitude) < 0.0005) {
        return;
      }
      geocodedFor.current = { latitude, longitude };
      geocodeRef.current?.abort();
      const controller = new AbortController();
      geocodeRef.current = controller;
      setResolvingPlace(true);
      api
        .reverseGeocode(latitude, longitude, controller.signal)
        .then((place) => {
          setLocation((current) =>
            current
              ? {
                  ...current,
                  displayName: place.displayName,
                  city: place.city,
                  state: place.state,
                  country: place.country,
                  postcode: place.postcode,
                  neighbourhood: place.neighbourhood,
                  waterFeature: place.waterFeature,
                  geocoding: place.cached ? 'cached' : 'nominatim',
                }
              : current,
          );
        })
        .catch((cause) => {
          // A missing place name never blocks a report — the coordinates are what matter.
          if (!isAbortError(cause)) geocodedFor.current = null;
        })
        .finally(() => {
          if (!controller.signal.aborted) setResolvingPlace(false);
        });
    },
    [api, settings.demoMode],
  );

  /** Ask Overpass which water body this point is next to. Failure leaves the field unknown. */
  const identifyWater = useCallback(
    (latitude: number, longitude: number) => {
      if (settings.demoMode) return;
      const previous = waterFoundFor.current;
      // Overpass is donated infrastructure: a GPS jitter of a few metres must not re-query it.
      if (previous && Math.abs(previous.latitude - latitude) < 0.002 && Math.abs(previous.longitude - longitude) < 0.002) {
        return;
      }
      waterFoundFor.current = { latitude, longitude };
      overpassRef.current?.abort();
      const controller = new AbortController();
      overpassRef.current = controller;
      setIdentifyingWater(true);
      api
        .nearbyWaterBodies(latitude, longitude, undefined, controller.signal)
        .then((response) => {
          const named = response.nearestNamed;
          setWaterBody(named);
          if (named) {
            setLocation((current) => (current ? { ...current, waterFeature: named.name } : current));
          }
        })
        .catch((cause) => {
          // Not knowing the water body never blocks a report; allow a later retry.
          if (!isAbortError(cause)) waterFoundFor.current = null;
        })
        .finally(() => {
          if (!controller.signal.aborted) setIdentifyingWater(false);
        });
    },
    [api, settings.demoMode],
  );

  const start = useCallback(() => {
    if (!geolocationSupported()) {
      setError('This browser cannot read a location here. Location needs HTTPS (or localhost).');
      return;
    }
    if (watchRef.current !== null) return;

    setError(null);
    setLocating(true);
    setTracking(true);
    watchRef.current = navigator.geolocation.watchPosition(
      (position) => {
        const { latitude, longitude, accuracy } = position.coords;
        setLocating(false);
        setError(null);
        setLocation((current) => ({
          ...(current ?? { source: 'browser_geolocation' as const, geocoding: 'unresolved' as const }),
          latitude,
          longitude,
          accuracyM: accuracy,
          source: 'browser_geolocation',
          geocoding: current?.geocoding ?? 'unresolved',
        }));
        resolvePlace(latitude, longitude);
        identifyWater(latitude, longitude);
      },
      (cause) => {
        setLocating(false);
        setError(describe(cause));
        // A denied permission never resolves on retry, so release the watch rather than spin.
        if (cause.code === cause.PERMISSION_DENIED) stop();
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 },
    );
  }, [resolvePlace, identifyWater, stop]);

  useEffect(() => stop, [stop]);

  return { location, waterBody, identifyingWater, tracking, locating, error, resolvingPlace, start, stop };
}
