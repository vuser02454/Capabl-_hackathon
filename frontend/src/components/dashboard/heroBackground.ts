import type { RiskLevel } from '../../types/agents';

/**
 * Real photographs (Wikimedia Commons, freely licensed), one per risk band — a clear city
 * skyline, an aerial view of photochemical smog, and a smog-choked skyline at dusk — so the
 * dashboard's background genuinely gets more polluted as the coordinator's overall risk rises,
 * the same "worse state -> more polluted scenery" idea as the landing page, but distinct
 * imagery rather than reused frames.
 */
export function heroBackgroundFor(level: RiskLevel | null): string {
  if (level === 'HIGH') return '/dashboard-bg/risk-high.jpg';
  if (level === 'MODERATE') return '/dashboard-bg/risk-moderate.jpg';
  return '/dashboard-bg/risk-low.jpg';
}
