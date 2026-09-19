import registry from '@shared/locations.json';
import { AppError } from '../services/errors';
import type { MapStation, WaterBody } from '../types/environment';

/** Location profile shared with the backend (shared/locations.json). */
export interface LocationProfile {
  id: string;
  name: string;
  region: string;
  lat: number;
  lon: number;
  aliases: string[];
  air: { stationId: string; stationName: string; pm25: number | null; pm10: number | null; no2: number | null; o3: number | null };
  water: {
    sensorId: string;
    sensorName: string;
    status: 'online' | 'degraded' | 'offline';
    ph: number | null;
    turbidity: number | null;
    temperature: number | null;
  };
  waste: { cameraId: string; cameraName: string; plastic: number; paper: number; other: number };
  trend: { air: number; water: number; waste: number };
  map: { stations: MapStation[]; waterBodies: WaterBody[] };
}

const data = registry as unknown as { locations: LocationProfile[]; noCoverage: string[] };

export const LOCATIONS: LocationProfile[] = data.locations;
export const NO_COVERAGE: string[] = data.noCoverage;

const normalise = (name: string) => name.trim().toLowerCase().replace(/[-_]/g, ' ').split(/\s+/).join(' ');

export function findLocation(name: string): LocationProfile | undefined {
  const key = normalise(name);
  return LOCATIONS.find((location) =>
    [location.id, location.name, ...location.aliases].some((candidate) => normalise(candidate) === key),
  );
}

/** Resolve a user-entered location or throw a user-friendly AppError. */
export function resolveLocation(name: string): LocationProfile {
  const key = normalise(name ?? '');
  if (!key) throw new AppError('INVALID_LOCATION', 'Please choose a location to analyze.');

  const location = findLocation(name);
  if (location) return location;

  const uncovered = NO_COVERAGE.find((candidate) => normalise(candidate) === key);
  if (uncovered) {
    throw new AppError('NO_MONITORING_DATA', `No monitoring stations are deployed in ${uncovered} yet.`);
  }
  throw new AppError('INVALID_LOCATION', `'${name.trim()}' is not a recognised monitoring location.`);
}

/**
 * The preset monitoring area closest to a coordinate pair.
 *
 * Used only by Demo Mode, which has fixtures for the preset areas and nothing else. When the
 * user has picked a real point, Demo Mode renders the nearest preset's fixtures — labelled as
 * demo data throughout the UI, so this is never presented as a reading from their location.
 */
export function nearestLocation(latitude: number, longitude: number): LocationProfile {
  // Equirectangular approximation: adequate for ranking a handful of cities, and it avoids
  // pulling in a full haversine for a demo-only fallback.
  const distanceSq = (location: LocationProfile) => {
    const dLat = location.lat - latitude;
    const dLon = (location.lon - longitude) * Math.cos((latitude * Math.PI) / 180);
    return dLat * dLat + dLon * dLon;
  };
  return LOCATIONS.reduce((closest, location) => (distanceSq(location) < distanceSq(closest) ? location : closest));
}
