/**
 * The three ways a worker can put a report on the map, in one panel.
 *
 * The order on screen is the order of the location hierarchy: device GPS first because it is the
 * only one that measures where the worker actually is, then a place search, then a map tap. Each
 * later option exists because the one above it can fail, and none of them is allowed to block the
 * report — a worker who cannot get any location still gets to file.
 *
 * Two rules are enforced here rather than left to the caller:
 *
 *   A failed lookup never replaces a fix that already exists. Search and GPS failures set a
 *   message; they do not clear `fix`. That is the "never overwrite a confirmed GPS location with
 *   a failed lookup" rule made structural.
 *
 *   "Location captured" is shown only when a real fix exists, because `status === 'ready'` is set
 *   solely by a successful GPS callback or a deliberate choice. There is no code path that can
 *   show the confirmation without coordinates behind it.
 */
import { Crosshair, Loader2, MapPin } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { Fix } from '../../hooks/useGeolocation';
import { useGeolocation } from '../../hooks/useGeolocation';
import { useIndiaCheck } from '../../hooks/useIndiaCheck';
import { Button } from '../ui/Button';
import { PlaceSearch } from './PlaceSearch';
import { SafetyMap, type MapMarker } from './SafetyMap';

/** Fallback view before anything is located. Bengaluru — the project's existing demo locale. */
const DEFAULT_CENTER: [number, number] = [12.9716, 77.5946];

const SOURCE_LABEL: Record<string, string> = {
  browser_gps: 'Device GPS',
  text_search: 'Location search',
  manual_map: 'Selected on map',
};

export interface LocationPickerValue {
  fix: Fix | null;
  confirmed: boolean;
}

export function LocationPicker({
  value,
  onChange,
  mapHeight = 220,
}: {
  value: LocationPickerValue;
  onChange: (next: LocationPickerValue) => void;
  mapHeight?: number;
}) {
  const geo = useGeolocation();
  const india = useIndiaCheck();
  const [pickOnMap, setPickOnMap] = useState(false);

  const { fix, confirmed } = value;

  /** Any new location invalidates a previous confirmation — the worker confirms what they see. */
  const adopt = (next: Fix | null) => onChange({ fix: next, confirmed: false });

  const findMe = () => {
    setPickOnMap(false);
    geo.locate();
  };

  /* The hook owns the GPS result; lift it into the form's state once per successful fix.
     Keyed on `capturedAt` so a repeat press of Find My Location is adopted as a new fix, while a
     re-render with the same fix is not — mirroring this during render would loop. */
  const adopted = useRef<string | null>(null);
  useEffect(() => {
    const found = geo.fix;
    if (!found || geo.status !== 'ready' || found.source !== 'browser_gps') return;
    if (adopted.current === found.capturedAt) return;
    adopted.current = found.capturedAt;
    /* A GPS fix has not been country-checked by anything yet, so it is verified before being
       adopted. A rejected fix is NOT silently moved into India — it is discarded and the reason
       shown, leaving search and map selection available. */
    void india.check(found.latitude, found.longitude).then((verdict) => {
      if (verdict.accepted) onChange({ fix: found, confirmed: false });
    });
  }, [geo.fix, geo.status, onChange, india]);

  const startMapPick = () => {
    setPickOnMap(true);
    // Seed with wherever the map is already looking, so there is something to drag from.
    if (!fix) {
      adopt({ latitude: DEFAULT_CENTER[0], longitude: DEFAULT_CENTER[1], accuracy: 0,
              source: 'manual_map', capturedAt: new Date().toISOString() });
    }
  };

  const markers: MapMarker[] = fix
    ? [{ id: 'chosen', latitude: fix.latitude, longitude: fix.longitude, kind: 'me',
         title: (fix.source ? SOURCE_LABEL[fix.source] : null) ?? 'Selected location' }]
    : [];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" icon={geo.isLocating ? Loader2 : Crosshair}
                loading={geo.isLocating} onClick={findMe}>
          Find My Location
        </Button>
        <Button size="sm" variant="ghost" icon={MapPin} onClick={startMapPick}>
          Select Location on Map
        </Button>
      </div>

      <PlaceSearch
        onChoose={(choice) => {
          setPickOnMap(false);
          adopt({ latitude: choice.latitude, longitude: choice.longitude, accuracy: 0,
                  source: 'text_search', label: choice.label,
                  capturedAt: new Date().toISOString() });
        }}
      />

      {/* GPS problems and search problems are reported separately: they have different remedies. */}
      {india.rejection && (
        <p role="status" className="rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-xs text-risk-high">
          {india.rejection} You can search for a location instead.
        </p>
      )}

      {geo.message && (
        <p role="status" className="rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
          {geo.message}{' '}
          {(geo.status === 'timeout' || geo.status === 'unavailable' || geo.status === 'error') && (
            <button type="button" onClick={findMe} className="font-semibold underline underline-offset-2">
              Try again
            </button>
          )}
        </p>
      )}
      {fix && (
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="text-xs text-fg">
            📍 Location captured{' '}
            <span className="text-fg-muted">
              · {(fix.source ? SOURCE_LABEL[fix.source] : null) ?? fix.source ?? 'Selected location'}
              {fix.source === 'browser_gps' && ` · Accuracy: ±${Math.round(fix.accuracy)} m`}
            </span>
          </p>
          {fix.label && <p className="mt-0.5 truncate text-[11px] text-fg-muted">{fix.label}</p>}
          <p className="mt-0.5 font-mono text-[10.5px] text-fg-subtle">
            {fix.latitude.toFixed(5)}, {fix.longitude.toFixed(5)}
          </p>
          {pickOnMap && <p className="mt-1 text-[11px] text-fg-muted">Tap the map to move the pin.</p>}

          <div className="mt-2">
            <SafetyMap
              markers={markers}
              center={[fix.latitude, fix.longitude]}
              zoom={16}
              height={mapHeight}
              recenterTo={[fix.latitude, fix.longitude]}
              onPick={pickOnMap
                ? (latitude, longitude) => {
                    void india.check(latitude, longitude).then((verdict) => {
                      if (verdict.accepted) {
                        adopt({ latitude, longitude, accuracy: 0, source: 'manual_map',
                                capturedAt: new Date().toISOString() });
                      }
                    });
                  }
                : undefined}
            />
          </div>

          <Button className="mt-2" size="sm" variant={confirmed ? 'ghost' : 'primary'}
                  disabled={confirmed} onClick={() => onChange({ fix, confirmed: true })}>
            {confirmed ? 'Location confirmed ✓' : 'Confirm Location'}
          </Button>
        </div>
      )}

      <p className="text-[11px] text-fg-subtle">
        Location is optional — you can submit without it.
      </p>
    </div>
  );
}
