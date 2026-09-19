/**
 * Location picker for the dashboard.
 *
 * Three ways to answer "where?", in one control:
 *   - the preset monitoring areas (shared/locations.json), which Demo Mode also uses;
 *   - a free-text search, resolved by the backend through Nominatim to real coordinates;
 *   - "Use My Location", a one-shot browser geolocation fix, reverse-geocoded by the backend.
 *
 * The browser never calls Nominatim itself. Every external lookup goes React -> FastAPI ->
 * provider, so the throttle, cache and identifying User-Agent that Nominatim's usage policy
 * requires live in one place (backend/services/geocoding_service.py).
 *
 * Search results are the provider's own. Nothing here invents a coordinate: a query that matches
 * nothing says so.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronDown, Crosshair, LoaderCircle, MapPin, Search, TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import { findLocation, LOCATIONS } from '../../data/locations';
import type { BrowserLocationState } from '../../hooks/useBrowserLocation';
import { MIN_QUERY_LENGTH, usePlaceSearch } from '../../hooks/usePlaceSearch';
import { cn } from '../../lib/format';
import type { SelectedLocation } from '../../types/agents';
import type { PlaceMatch } from '../../types/environment';
import { Button } from '../ui/Button';

interface LocationSelectorProps {
  value: string;
  /** The exact point in use, when one was picked. Null means the named preset is in use. */
  point: SelectedLocation | null;
  onChange: (location: string) => void;
  onSelectPoint: (point: SelectedLocation) => void;
  /**
   * Owned by LocationBar, not created here: one hook instance means at most one browser
   * permission prompt, however many times this dropdown mounts.
   */
  browser: BrowserLocationState;
  disabled?: boolean;
}

export function LocationSelector({ value, point, onChange, onSelectPoint, browser, disabled }: LocationSelectorProps) {
  const { api, settings } = useSettings();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const profile = findLocation(value);

  const searchPlaces = useCallback(
    (text: string, limit: number, signal: AbortSignal) => api.searchPlaces(text, limit, signal),
    [api],
  );

  // Demo Mode runs entirely in the browser against the preset dataset, so there is no backend to
  // search and no honest place name to resolve a GPS fix to.
  const liveBackend = !settings.demoMode;
  const search = usePlaceSearch(query, { search: searchPlaces, disabled: !liveBackend });

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const normalized = query.trim().toLowerCase();
  const presets = LOCATIONS.filter(
    (location) =>
      !normalized ||
      location.name.toLowerCase().includes(normalized) ||
      location.region.toLowerCase().includes(normalized) ||
      location.aliases.some((alias) => alias.includes(normalized)),
  );

  const choosePreset = (name: string) => {
    onChange(name);
    setOpen(false);
    setQuery('');
    search.reset();
  };

  /** A Nominatim match is a real coordinate pair, so it becomes the analysis point. */
  const chooseMatch = (match: PlaceMatch) => {
    onSelectPoint({
      latitude: match.latitude,
      longitude: match.longitude,
      displayName: match.displayName,
      source: 'manual',
      geocoding: 'nominatim',
    });
    setOpen(false);
    setQuery('');
    search.reset();
  };

  const useMyLocation = async () => {
    const found = await browser.request();
    if (found) {
      onSelectPoint(found);
      setOpen(false);
      setQuery('');
      search.reset();
    }
  };

  const label = point ? point.displayName : (profile?.name ?? value);
  const sublabel = point
    ? `${point.source === 'browser' ? 'Browser location' : 'Manual search'} · ${point.latitude.toFixed(4)}, ${point.longitude.toFixed(4)}`
    : profile
      ? `${profile.region} · ${profile.lat.toFixed(2)}°N ${profile.lon.toFixed(2)}°E`
      : 'Unverified location';

  return (
    <div ref={containerRef} className="relative flex w-full flex-col gap-1.5 sm:w-auto sm:flex-row sm:items-center sm:gap-3">
      <span className="eyebrow">Location</span>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex h-11 w-full items-center gap-2.5 rounded-xl border border-black/10 bg-black/[0.04] px-3 text-left transition hover:border-black/15 hover:bg-black/[0.07] disabled:cursor-not-allowed disabled:opacity-60 sm:w-64"
      >
        <MapPin className="size-4 shrink-0 text-brand" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-fg">{label}</span>
          <span className="block truncate text-[10.5px] text-fg-subtle">{sublabel}</span>
        </span>
        <ChevronDown className={cn('size-4 shrink-0 text-fg-subtle transition-transform', open && 'rotate-180')} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="absolute top-full right-0 left-0 z-40 mt-2 overflow-hidden rounded-xl border border-black/10 bg-ink-850/95 shadow-2xl backdrop-blur-xl sm:right-auto sm:left-[76px] sm:w-96"
          >
            <div className="flex items-center gap-2 border-b border-black/[0.06] px-3">
              <Search className="size-3.5 shrink-0 text-fg-subtle" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== 'Enter') return;
                  // Enter takes a real search result when there is one, so a typed place name
                  // resolves to actual coordinates rather than a preset lookup.
                  if (search.matches.length > 0) chooseMatch(search.matches[0]);
                  else if (presets.length > 0) choosePreset(presets[0].name);
                }}
                placeholder={liveBackend ? 'Search any place…' : 'Search a monitored city…'}
                aria-label="Search location"
                className="h-10 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
              />
              {search.searching && <LoaderCircle className="size-3.5 shrink-0 animate-spin text-fg-subtle" />}
            </div>

            <div className="border-b border-black/[0.06] p-1.5">
              <Button
                size="sm"
                variant="ghost"
                icon={Crosshair}
                loading={browser.locating}
                onClick={() => void useMyLocation()}
                className="w-full justify-start"
              >
                {browser.locating ? 'Locating…' : 'Use My Location'}
              </Button>
              {browser.error && (
                <p className="flex items-start gap-1.5 px-2.5 pt-1.5 pb-1 text-[10.5px] text-risk-moderate">
                  <TriangleAlert className="mt-px size-3 shrink-0" />
                  <span>{browser.error.message}</span>
                </p>
              )}
            </div>

            <ul role="listbox" className="max-h-72 overflow-y-auto p-1.5">
              {/* Provider results first: the user typed a place, not a preset id. */}
              {search.matches.length > 0 && (
                <li className="px-2.5 pt-1 pb-1.5 text-[10px] tracking-wide text-fg-subtle uppercase">
                  OpenStreetMap / Nominatim
                </li>
              )}
              {search.matches.map((match) => (
                <li key={`${match.displayName}-${match.latitude}-${match.longitude}`}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={false}
                    onClick={() => chooseMatch(match)}
                    className="flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition hover:bg-black/[0.05]"
                  >
                    <MapPin className="mt-0.5 size-3.5 shrink-0 text-brand" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-fg">{match.displayName}</span>
                      <span className="block text-[10.5px] text-fg-subtle tabular">
                        {match.latitude.toFixed(4)}, {match.longitude.toFixed(4)}
                        {match.isWater && ' · water feature'}
                      </span>
                    </span>
                  </button>
                </li>
              ))}

              {presets.length > 0 && (
                <li className="px-2.5 pt-2 pb-1.5 text-[10px] tracking-wide text-fg-subtle uppercase">
                  Monitored areas
                </li>
              )}
              {presets.map((location) => {
                const selected = !point && location.id === profile?.id;
                return (
                  <li key={location.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={selected}
                      onClick={() => choosePreset(location.name)}
                      className={cn('flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition hover:bg-black/[0.05]', selected && 'bg-black/[0.04]')}
                    >
                      <span className="grid size-8 place-items-center rounded-lg border border-black/[0.06] bg-black/[0.03] text-[10px] font-semibold text-fg-muted">
                        {location.name.slice(0, 3).toUpperCase()}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm text-fg">{location.name}</span>
                        <span className="block text-[10.5px] text-fg-subtle">
                          {location.region} · {location.map.stations.length} stations
                        </span>
                      </span>
                      {selected && <Check className="size-4 text-brand" />}
                    </button>
                  </li>
                );
              })}

              {search.error && (
                <li className="px-2.5 py-2 text-xs text-risk-moderate">{search.error}</li>
              )}
              {search.empty && !search.error && presets.length === 0 && (
                <li className="px-2.5 py-2 text-xs text-fg-muted">No place matched “{query.trim()}”.</li>
              )}
              {!liveBackend && normalized.length >= MIN_QUERY_LENGTH && presets.length === 0 && (
                <li className="px-2.5 py-2 text-xs text-fg-muted">
                  Demo Mode searches the bundled monitored areas only. Switch off Demo Mode to search any place.
                </li>
              )}
            </ul>

            <div className="border-t border-black/[0.06] px-3 py-2 text-[10.5px] text-fg-subtle">
              {liveBackend
                ? `${LOCATIONS.length} monitored areas · type ${MIN_QUERY_LENGTH}+ characters to search OpenStreetMap`
                : `${LOCATIONS.length} monitored areas · Demo Mode`}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
