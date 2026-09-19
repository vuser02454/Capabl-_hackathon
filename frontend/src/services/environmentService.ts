import { resolveLocation } from '../data/locations';
import type { EnvironmentSnapshot } from '../types/environment';
import type { ApiClient } from './apiClient';
import { generateHistory } from './history';

/** Map layout + historical series for a location, from local data (demo) or the API (live). */
export async function loadEnvironment(
  location: string,
  mode: 'demo' | 'live',
  api: ApiClient,
  signal?: AbortSignal,
): Promise<EnvironmentSnapshot> {
  if (mode === 'live') return api.environment(location, signal);

  const profile = resolveLocation(location);
  const now = new Date();
  return {
    location: { id: profile.id, name: profile.name, region: profile.region, lat: profile.lat, lon: profile.lon },
    stations: profile.map.stations,
    waterBodies: profile.map.waterBodies,
    history: {
      '24h': generateHistory(profile, '24h', now),
      '7d': generateHistory(profile, '7d', now),
      '30d': generateHistory(profile, '30d', now),
    },
  };
}
