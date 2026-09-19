/**
 * Debounced place search through the backend (FastAPI -> Nominatim).
 *
 * The browser never talks to Nominatim directly. Nominatim's usage policy caps requests at one
 * per second for the whole application, which only the backend can honour — it owns the throttle,
 * the cache and the identifying User-Agent (backend/services/geocoding_service.py). The debounce
 * here is the second line of defence: one request per pause in typing, not one per keystroke.
 *
 * Results are always the provider's own. A query that matches nothing returns an empty list and
 * says so; it never falls back to guessing coordinates.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { isAbortError } from '../services/errors';
import type { PlaceMatch } from '../types/environment';

export const SEARCH_DEBOUNCE_MS = 400;
/** Below this, a query matches half the planet and wastes a request. */
export const MIN_QUERY_LENGTH = 3;

export interface PlaceSearchState {
  matches: PlaceMatch[];
  searching: boolean;
  /** Set when the provider could not be reached — distinct from "no matches". */
  error: string | null;
  /** True when a complete search returned nothing. */
  empty: boolean;
  reset: () => void;
}

export interface PlaceSearchOptions {
  search: (query: string, limit: number, signal: AbortSignal) => Promise<{ matches: PlaceMatch[] }>;
  limit?: number;
  /** Skip searching entirely (Demo Mode has no backend to ask). */
  disabled?: boolean;
}

export function usePlaceSearch(query: string, { search, limit = 6, disabled = false }: PlaceSearchOptions): PlaceSearchState {
  const [matches, setMatches] = useState<PlaceMatch[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [empty, setEmpty] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setMatches([]);
    setSearching(false);
    setError(null);
    setEmpty(false);
  }, []);

  const trimmed = query.trim();

  useEffect(() => {
    if (disabled || trimmed.length < MIN_QUERY_LENGTH) {
      controllerRef.current?.abort();
      controllerRef.current = null;
      setMatches([]);
      setSearching(false);
      setError(null);
      setEmpty(false);
      return;
    }

    setSearching(true);
    setError(null);
    const timer = setTimeout(() => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      search(trimmed, limit, controller.signal)
        .then((response) => {
          if (controller.signal.aborted) return;
          setMatches(response.matches);
          setEmpty(response.matches.length === 0);
          setSearching(false);
        })
        .catch((cause) => {
          if (isAbortError(cause) || controller.signal.aborted) return;
          setMatches([]);
          setEmpty(false);
          setError('Location search is temporarily unavailable. Please try again.');
          setSearching(false);
        });
    }, SEARCH_DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [trimmed, limit, disabled, search]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  return { matches, searching, error, empty, reset };
}
