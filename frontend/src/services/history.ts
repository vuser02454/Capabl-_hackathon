import type { LocationProfile } from '../data/locations';
import { roundHalfUp } from '../lib/risk';
import { seeded } from '../lib/rng';
import type { TrendPoint, TrendRange } from '../types/environment';

/** range -> [points, hours between points]; mirrors backend/data/history.py */
export const HISTORY_RANGES: Record<TrendRange, [number, number]> = {
  '24h': [24, 1],
  '7d': [28, 6],
  '30d': [30, 24],
};

const ramp = (current: number, startRatio: number, progress: number) =>
  current * (startRatio + (1 - startRatio) * progress);

export function generateHistory(location: LocationProfile, range: TrendRange, now = new Date()): TrendPoint[] {
  const [points, step] = HISTORY_RANGES[range];
  const rng = seeded(`history:${location.id}:${range}`);
  const { air, water, waste, trend } = location;
  const totalWaste = waste.plastic + waste.paper + waste.other;
  const anchor = new Date(now);
  anchor.setUTCMinutes(0, 0, 0);

  const series: TrendPoint[] = [];
  for (let i = 0; i < points; i += 1) {
    const progress = i / (points - 1);
    const hoursAgo = (points - 1 - i) * step;
    const rAir = rng();
    const rWater = rng();
    const rWaste = rng();
    const latest = i === points - 1;
    const diurnal = Math.sin((2 * Math.PI * hoursAgo) / 24);

    const pm25 =
      air.pm25 === null
        ? null
        : latest
          ? air.pm25
          : roundHalfUp(ramp(air.pm25, trend.air ?? 0.75, progress) * (1 + 0.1 * diurnal) * (1 + (rAir - 0.5) * 0.18), 1);

    const turbidity =
      water.turbidity === null
        ? null
        : latest
          ? water.turbidity
          : roundHalfUp(ramp(water.turbidity, trend.water ?? 0.75, progress) * (1 + (rWater - 0.5) * 0.3), 1);

    const wasteCount = latest
      ? totalWaste
      : roundHalfUp(ramp(totalWaste, trend.waste ?? 0.75, progress) * (1 + (rWaste - 0.5) * 0.4), 0);

    series.push({
      hoursAgo,
      timestamp: new Date(anchor.getTime() - hoursAgo * 3_600_000).toISOString(),
      pm25,
      turbidity,
      wasteCount,
    });
  }
  return series;
}
