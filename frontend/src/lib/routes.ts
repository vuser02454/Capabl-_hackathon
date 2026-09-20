export type RouteId =
  // C3 Safety Intelligence — the primary product.
  | 'safety' | 'analyze' | 'patterns'
  // Worker experience (mobile-first) and the admin safety map.
  | 'worker-report' | 'worker-map' | 'worker-alerts' | 'worker-my-reports'
  | 'admin-dashboard' | 'admin-map' | 'admin-reports' | 'admin-hotspots' | 'admin-announcements'
  | 'admin-worker-routes' | 'worker-my-routes' | 'notifications'
  // Retained environmental routes: reachable by URL, no longer in the primary navigation.
  | 'landing' | 'dashboard' | 'map' | 'air' | 'water' | 'waste' | 'coordinator' | 'reports'
  | 'settings' | 'how-it-works';

export const ROUTE_PATHS: Record<RouteId, string> = {
  safety: '/safety',
  'worker-report': '/worker/report',
  'worker-map': '/worker/map',
  'worker-alerts': '/worker/alerts',
  'worker-my-reports': '/worker/my-reports',
  'admin-dashboard': '/admin/dashboard',
  'admin-map': '/admin/map',
  'admin-reports': '/admin/reports',
  'admin-hotspots': '/admin/hotspots',
  'admin-announcements': '/admin/announcements',
  'admin-worker-routes': '/admin/worker-routes',
  'worker-my-routes': '/worker/my-routes',
  notifications: '/notifications',
  analyze: '/safety/analyze',
  patterns: '/safety/patterns',
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
  safety: { title: 'Safety Intelligence', subtitle: 'Incident precursor detection across all reports' },
  'worker-report': { title: 'Report a Safety Issue', subtitle: 'Your report goes straight to the safety team' },
  'worker-map': { title: 'Safety Map', subtitle: 'Published safety alerts near you' },
  'worker-alerts': { title: 'Safety Alerts', subtitle: 'Published by the safety team' },
  'worker-my-reports': { title: 'My Reports', subtitle: 'The safety reports you have submitted' },
  'admin-dashboard': { title: 'Safety Admin', subtitle: 'Reports, candidate hotspots and review queue' },
  'admin-map': { title: 'Safety Map', subtitle: 'Reports, candidate hotspots and published alerts' },
  'admin-reports': { title: 'All Reports', subtitle: 'Every submitted report with its evidence' },
  'admin-hotspots': { title: 'Candidate Hotspots', subtitle: 'Awaiting human review — nothing is published automatically' },
  'admin-announcements': { title: 'Announcements', subtitle: 'Alerts published to workers' },
  'admin-worker-routes': { title: 'Worker Route Intelligence', subtitle: 'Recorded routing decisions and their evidence' },
  'worker-my-routes': { title: 'My Routes', subtitle: 'Routes you have requested' },
  notifications: { title: 'Notifications', subtitle: 'Messages between workers and the safety team' },
  analyze: { title: 'Analyze Safety Report', subtitle: 'Four agents extract, classify, compare and advise' },
  patterns: { title: 'Pattern Intelligence', subtitle: 'Recurring hazards, locations and root causes' },
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
  return match ? match[0] : 'safety';
}
