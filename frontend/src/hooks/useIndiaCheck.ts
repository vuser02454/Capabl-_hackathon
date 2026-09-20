/**
 * India-only validation for a coordinate the user produced.
 *
 * Three things can produce a coordinate in this app: a search result, a GPS fix, and a map tap.
 * Search results are already country-filtered by the backend (Nominatim's `countrycodes`, then a
 * re-check of each result's structured `country_code`), so only the other two reach this hook.
 *
 * Validation happens on the server by reverse geocoding, not by a latitude/longitude box in the
 * browser: a rectangle around India also contains parts of Nepal, Pakistan, Bangladesh and
 * Myanmar. The backend keeps a cheap box as a pre-filter so an obviously distant point costs no
 * network call, but the box never decides that something IS in India.
 *
 * An unreachable geocoder ACCEPTS the location and marks it unverified. Blocking a worker
 * standing in a yard in Pune because a third-party service is down would be the worse failure.
 */
import { useCallback, useState } from 'react';
import { useSettings } from '../context/SettingsContext';

export interface IndiaVerdict {
  accepted: boolean;
  /** False when the country could not be confirmed — the location is used, but flagged. */
  verified: boolean;
  countryCode: string | null;
  reason: string | null;
  place: string | null;
}

export function useIndiaCheck() {
  const { api } = useSettings();
  const [checking, setChecking] = useState(false);
  const [rejection, setRejection] = useState<string | null>(null);

  /** Returns the verdict, and records a rejection message for the caller to display. */
  const check = useCallback(async (latitude: number, longitude: number): Promise<IndiaVerdict> => {
    setChecking(true);
    setRejection(null);
    try {
      const verdict = await api.verifyLocationInIndia(latitude, longitude);
      if (!verdict.accepted) setRejection(verdict.reason ?? 'This location is outside India.');
      return verdict;
    } catch {
      // The check itself failed. Same rule as a failed reverse geocode on the server: accept the
      // location rather than lose it, and say it is unverified.
      return { accepted: true, verified: false, countryCode: null, place: null,
               reason: 'The country could not be confirmed.' };
    } finally {
      setChecking(false);
    }
  }, [api]);

  const clear = useCallback(() => setRejection(null), []);

  return { check, checking, rejection, clear };
}
