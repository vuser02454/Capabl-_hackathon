import { useState } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { RANGE_LABELS, relativeChange, trendAxisLabel } from '../../lib/format';
import type { TrendPoint, TrendRange } from '../../types/environment';
import { AGENT_META } from '../agents/agentMeta';
import { ErrorState } from '../ui/ErrorState';
import { SectionHeader, SegmentedControl } from '../ui/primitives';
import { TrendChart } from './TrendChart';

export const RANGE_OPTIONS: Array<{ value: TrendRange; label: string }> = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
];

type MetricKey = 'pm25' | 'turbidity' | 'wasteCount';

export function seriesFor(history: TrendPoint[], range: TrendRange, key: MetricKey) {
  return history.map((point) => ({ label: trendAxisLabel(range, point.timestamp), value: point[key] }));
}

export function seriesChange(history: TrendPoint[], key: MetricKey) {
  const values = history.map((point) => point[key]).filter((value): value is number => value !== null);
  return values.length > 1 ? relativeChange(values[0], values[values.length - 1]) : null;
}

function TrendTable({ history, range }: { history: TrendPoint[]; range: TrendRange }) {
  return (
    <div className="glass max-h-[340px] overflow-auto p-2">
      <table className="w-full min-w-[480px] text-left text-xs">
        <thead className="sticky top-0 bg-ink-850/95 backdrop-blur">
          <tr className="text-[10.5px] tracking-wider text-fg-subtle uppercase">
            <th className="px-3 py-2 font-medium">Time</th>
            <th className="px-3 py-2 text-right font-medium">PM2.5 (µg/m³)</th>
            <th className="px-3 py-2 text-right font-medium">Turbidity (NTU)</th>
            <th className="px-3 py-2 text-right font-medium">Waste objects</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {[...history].reverse().map((point) => (
            <tr key={point.timestamp} className="border-t border-black/[0.04]">
              <td className="px-3 py-1.5 text-fg-muted">{trendAxisLabel(range, point.timestamp)}</td>
              <td className="px-3 py-1.5 text-right text-fg">{point.pm25 ?? '—'}</td>
              <td className="px-3 py-1.5 text-right text-fg">{point.turbidity ?? '—'}</td>
              <td className="px-3 py-1.5 text-right text-fg">{point.wasteCount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TrendsSection() {
  const { environment, environmentError, runAnalysis, display } = useAnalysis();
  const [range, setRange] = useState<TrendRange>('24h');
  const [view, setView] = useState<'chart' | 'table'>('chart');
  const history = environment?.history[range] ?? [];
  const latest = history[history.length - 1];

  return (
    <section className="space-y-4">
      <SectionHeader
        eyebrow="History"
        title="Environmental Trends"
        subtitle={`${RANGE_LABELS[range]}${environment ? ` · ${environment.location.name}` : ''}`}
        actions={
          <>
            <SegmentedControl
              ariaLabel="Trend view"
              layoutId="trend-view"
              options={[
                { value: 'chart', label: 'Charts' },
                { value: 'table', label: 'Table' },
              ]}
              value={view}
              onChange={setView}
            />
            <SegmentedControl ariaLabel="Time range" layoutId="trend-range" options={RANGE_OPTIONS} value={range} onChange={setRange} />
          </>
        }
      />

      {environmentError ? (
        <ErrorState compact error={environmentError} onRetry={() => void runAnalysis({ instant: true })} />
      ) : !environment ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {[0, 1, 2].map((index) => (
            <div key={index} className="skeleton h-[270px] rounded-2xl" />
          ))}
        </div>
      ) : view === 'table' ? (
        <TrendTable history={history} range={range} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <TrendChart
            title="PM2.5 Trend"
            icon={AGENT_META.air.icon}
            color={AGENT_META.air.color}
            unit="µg/m³"
            decimals={1}
            data={seriesFor(history, range, 'pm25')}
            rangeLabel={display.air && !display.air.isMock ? `${RANGE_LABELS[range]} · demo history` : RANGE_LABELS[range]}
            threshold={{ value: 15, label: 'WHO guideline' }}
            current={latest?.pm25}
            change={seriesChange(history, 'pm25')}
          />
          <TrendChart
            title="Water Turbidity Trend"
            icon={AGENT_META.water.icon}
            color={AGENT_META.water.color}
            unit="NTU"
            decimals={1}
            data={seriesFor(history, range, 'turbidity')}
            rangeLabel={RANGE_LABELS[range]}
            threshold={{ value: 5, label: 'BIS limit' }}
            current={latest?.turbidity}
            change={seriesChange(history, 'turbidity')}
            emptyMessage="The turbidity probe on this sensor is not reporting — no series available."
            delay={0.05}
          />
          <TrendChart
            title="Waste Detection Count"
            icon={AGENT_META.waste.icon}
            color={AGENT_META.waste.color}
            unit="objects"
            variant="bar"
            data={seriesFor(history, range, 'wasteCount')}
            rangeLabel={RANGE_LABELS[range]}
            threshold={{ value: 15, label: 'High density' }}
            current={latest?.wasteCount}
            change={seriesChange(history, 'wasteCount')}
            delay={0.1}
          />
        </div>
      )}
    </section>
  );
}
