export type RouteId = 'landing' | 'dashboard' | 'map' | 'air' | 'water' | 'waste' | 'coordinator' | 'reports' | 'settings' | 'how-it-works';

export const ROUTE_PATHS: Record<RouteId, string> = {
  landing: '/',
  dashboard: '/dashboard',
  map: '/map',
  air: '/agents/air',
  water: '/agents/water',
  waste: '/agents/waste',
  coordinator: '/coordinator',
  reports: '/reports',
  settings: '/settings',
  'how-it-works': '/how-it-works',
};

/** `landing` renders full-bleed outside AppLayout, so its entry is only here to keep the map total. */
export const PAGE_TITLES: Record<RouteId, { title: string; subtitle: string }> = {
  landing: { title: 'EcoSentinel AI', subtitle: 'Environmental intelligence, in real time' },
  dashboard: { title: 'Environmental Intelligence', subtitle: 'Multi-agent monitoring and risk assessment' },
  map: { title: 'Environmental Map', subtitle: 'Monitoring stations and spatial risk zones' },
  air: { title: 'Air Quality Agent', subtitle: 'Pollutant normalization, risk scoring and anomaly detection' },
  water: { title: 'Water Pollution Agent', subtitle: 'Visual pollution detection and explainable environmental investigation' },
  waste: { title: 'Waste Detection Agent', subtitle: 'Computer-vision litter detection and classification' },
  coordinator: { title: 'Coordinator Agent', subtitle: 'Cross-signal environmental reasoning' },
  reports: { title: 'Reports', subtitle: 'Structured environmental risk reports' },
  settings: { title: 'Settings', subtitle: 'Data sources, demo mode and system behaviour' },
  'how-it-works': { title: 'How EcoSentinel Works', subtitle: 'Independent specialist agents, one coordinating decision' },
};

export function parseRoute(hash: string): RouteId {
  const path = hash.replace(/^#/, '') || ROUTE_PATHS.landing;
  const match = (Object.entries(ROUTE_PATHS) as Array<[RouteId, string]>).find(([, value]) => value === path);
  return match ? match[0] : 'dashboard';
}
