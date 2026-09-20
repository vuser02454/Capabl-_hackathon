/**
 * Place search shared by the Report Issue form and the Safety Map.
 *
 * One component, because both screens ask the same question and a second implementation would
 * drift. Both go React → FastAPI → Nominatim; the browser never calls a provider directly, which
 * is the rule an architecture test already enforces.
 *
 * The important behaviour is that RESULTS ARE SHOWN AND THE USER PICKS ONE. The previous version
 * requested a single match and adopted it silently, which is wrong in a way that is easy to miss:
 * searching "Whitefield" returns Whitefield, New Hampshire before Whitefield, Bengaluru, so the
 * map jumped to another continent with no indication anything had been chosen. A list makes the
 * ambiguity visible and lets the worker resolve it.
 */
import { Loader2, MapPin, Search, X } from 'lucide-react';
import { useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import type { PlaceMatch } from '../../types/environment';
import { Button } from '../ui/Button';

/** Enough to show the alternatives without turning the panel into a page of results. */
const RESULT_LIMIT = 6;

export interface PlaceChoice {
  latitude: number;
  longitude: number;
  label: string;
}

export function PlaceSearch({
  onChoose,
  placeholder = 'Search location — Whitefield, KR Puram, Indiranagar…',
  label = 'Search location',
}: {
  onChoose: (choice: PlaceChoice) => void;
  placeholder?: string;
  label?: string;
}) {
  const { api } = useSettings();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlaceMatch[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async () => {
    const text = query.trim();
    if (!text) {
      // Empty input is not an error; it is simply nothing to look up.
      setError(null);
      setResults(null);
      return;
    }
    setSearching(true);
    setError(null);
    setResults(null);
    try {
      const { matches } = await api.searchPlaces(text, RESULT_LIMIT);
      // Filter out any results that are explicitly outside India
      const validMatches = matches.filter((m) => !m.countryCode || m.countryCode.toLowerCase() === 'in');
      setResults(validMatches);
      if (validMatches.length === 0) {
        setError(matches.length > 0
          ? 'Please select a location in India.'
          : `No locations found in India for “${text}”. Please select a location in India.`);
      }
    } catch (cause) {
      // A provider failure leaves any location already chosen exactly where it was.
      setError(cause instanceof Error
        ? `Location search is unavailable: ${cause.message}`
        : 'Location search is unavailable. You can still select a location on the map.');
    } finally {
      setSearching(false);
    }
  };

  const choose = (match: PlaceMatch) => {
    if (match.countryCode && match.countryCode.toLowerCase() !== 'in') {
      setError('Please select a location in India.');
      return;
    }
    onChoose({ latitude: match.latitude, longitude: match.longitude, label: match.displayName });
    setResults(null);
    setQuery(match.displayName.split(',')[0]);
  };

  return (
    <div className="space-y-1.5">
      <div className="flex gap-2">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') void search(); }}
          placeholder={placeholder}
          aria-label={label}
          className="min-w-0 flex-1 rounded-lg border border-black/[0.08] bg-black/[0.02] px-3 py-2 text-xs text-fg outline-none transition placeholder:text-fg-subtle focus:border-brand/40"
        />
        <Button size="sm" variant="ghost" icon={searching ? Loader2 : Search}
                loading={searching} onClick={() => void search()}>
          Search
        </Button>
        {results !== null && results.length > 0 && (
          <Button size="sm" variant="ghost" icon={X} onClick={() => { setResults(null); setError(null); }}>
            Close
          </Button>
        )}
      </div>

      {searching && <p role="status" className="text-[11px] text-fg-muted">Searching…</p>}

      {error && (
        <p role="status" className="rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
          {error}
        </p>
      )}

      {/* Showing place name, full display name, and coordinates explicitly allows the user to
          differentiate places like "Whitefield, Bengaluru" from "Whitefield, New Hampshire" before choosing. */}
      {results !== null && results.length > 0 && (
        <ul className="max-h-52 space-y-1 overflow-y-auto rounded-lg border border-black/[0.08] bg-black/[0.02] p-1">
          {results.map((match) => {
            const placeName = match.displayName.split(',')[0].trim();
            return (
              <li key={`${match.latitude},${match.longitude},${match.displayName}`}>
                <button
                  type="button"
                  onClick={() => choose(match)}
                  className="flex w-full items-start gap-2 rounded-md px-2.5 py-1.5 text-left transition hover:bg-brand/[0.08]"
                >
                  <MapPin className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-[12px] text-fg">{placeName}</span>
                    <span className="block truncate text-[11px] text-fg-muted">{match.displayName}</span>
                    <span className="block font-mono text-[10px] text-fg-subtle">
                      {match.latitude.toFixed(5)}, {match.longitude.toFixed(5)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
