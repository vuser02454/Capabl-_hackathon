/**
 * Safety Intelligence dashboard — the aggregate view a safety officer opens first.
 *
 * Ordered by what someone acts on: how many reports and how severe, then which specific hazards
 * and locations are recurring, then the individual reports. Emerging patterns sit high because a
 * pattern nobody noticed is the thing this product exists to surface — a single report is already
 * visible to whoever filed it.
 */
import { AlertTriangle, Layers, ListChecks, MapPin, RefreshCw, TrendingUp } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { DataModeBadge } from '../components/ui/DataModeBadge';
import { MetricCard } from '../components/ui/MetricCard';
import { RiskBadge } from '../components/ui/RiskBadge';
import { useSettings } from '../context/SettingsContext';
import { toDisplayRisk, type RiskLevel, type SafetyOverview } from '../types/safety';

const RISK_COLOR: Record<RiskLevel, string> = {
  HIGH: '#dc2626',
  MEDIUM: '#d97706',
  LOW: '#059669',
};

export function SafetyDashboardPage() {
  const { api } = useSettings();
  const [data, setData] = useState<SafetyOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await api.safetyOverview());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load safety analytics.');
    } finally {
      setBusy(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const seed = async () => {
    setBusy(true);
    try {
      await api.seedSafetyCorpus(false);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not seed the demo corpus.');
      setBusy(false);
    }
  };

  if (error) {
    return (
      <DashboardCard title="Safety Intelligence" subtitle="Analytics unavailable" icon={AlertTriangle} iconColor="#dc2626">
        <p className="text-sm text-fg-muted">{error}</p>
        <Button className="mt-3" size="sm" variant="ghost" icon={RefreshCw} onClick={() => void load()}>
          Retry
        </Button>
      </DashboardCard>
    );
  }

  if (!data) {
    return (
      <DashboardCard title="Safety Intelligence" subtitle="Loading analytics…" icon={Layers} iconColor="#2563eb">
        <div className="skeleton h-24 w-full" />
      </DashboardCard>
    );
  }

  const { riskDistribution: dist } = data;
  const distributionData = (['HIGH', 'MEDIUM', 'LOW'] as RiskLevel[]).map((level) => ({
    level,
    count: dist[level],
  }));

  return (
    <div className="space-y-4">
      {data.totalReports === 0 ? (
        <DashboardCard title="No reports yet" subtitle="Load the synthetic demo corpus to begin" icon={Layers} iconColor="#2563eb">
          <p className="text-sm text-fg-muted">
            The pattern engine needs a corpus to compare against. Loading the demo set analyses
            {' '}synthetic reports written for this demonstration.
          </p>
          <Button className="mt-3" variant="primary" loading={busy} onClick={() => void seed()}>
            Load demo corpus
          </Button>
        </DashboardCard>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Total Reports" value={data.totalReports}
                        hint={`${data.syntheticReports} synthetic · ${data.userReports} submitted`} />
            <MetricCard label="High Risk" value={dist.HIGH} status="critical"
                        progress={dist.HIGH / data.totalReports}
                        hint={`${Math.round((100 * dist.HIGH) / data.totalReports)}% of corpus`} />
            <MetricCard label="Medium Risk" value={dist.MEDIUM} status="elevated"
                        progress={dist.MEDIUM / data.totalReports}
                        hint={`${Math.round((100 * dist.MEDIUM) / data.totalReports)}% of corpus`} />
            <MetricCard label="Low Risk" value={dist.LOW} status="normal"
                        progress={dist.LOW / data.totalReports}
                        hint={`${Math.round((100 * dist.LOW) / data.totalReports)}% of corpus`} />
          </div>

          <DashboardCard
            title="Emerging Safety Patterns"
            subtitle="Recurring hazard + location combinations found across the corpus"
            icon={TrendingUp}
            iconColor="#2563eb"
            actions={<DataModeBadge tone="demo" label="Synthetic corpus" size="sm" />}
          >
            <p className="mb-3 text-[13px] leading-relaxed text-fg-muted">{data.trendSummary}</p>
            {data.emergingPatterns.length ? (
              <ul className="space-y-2">
                {data.emergingPatterns.slice(0, 5).map((pattern, index) => (
                  <li key={index} className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[13px] font-medium text-fg">{pattern.pattern}</span>
                      {pattern.count !== null && (
                        <span className="shrink-0 font-mono text-[11px] text-fg-muted">×{pattern.count}</span>
                      )}
                    </div>
                    {pattern.detail && <p className="mt-0.5 text-xs text-fg-muted">{pattern.detail}</p>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-fg-subtle">No hazard has recurred at one location three or more times yet.</p>
            )}
          </DashboardCard>

          <div className="grid gap-4 xl:grid-cols-5">
            <DashboardCard title="Risk Distribution" subtitle="Across all analysed reports" icon={Layers} iconColor="#2563eb" className="xl:col-span-2">
              {/* Plain CSS bars rather than a chart library: recharts' vertical layout needs an
                  explicit scale to size bars against and was rendering 2px slivers. This is
                  legible at any width and matches the ranked lists elsewhere on the page. */}
              <ul className="space-y-3">
                {distributionData.map((entry) => (
                  <li key={entry.level}>
                    <div className="mb-1 flex items-baseline justify-between">
                      <span className="text-[13px] font-medium text-fg">{entry.level}</span>
                      <span className="font-mono text-[11px] text-fg-muted">
                        {entry.count} · {Math.round((100 * entry.count) / data.totalReports)}%
                      </span>
                    </div>
                    <div className="h-2.5 overflow-hidden rounded-full bg-black/[0.06]">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${(100 * entry.count) / data.totalReports}%`,
                          background: RISK_COLOR[entry.level],
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </DashboardCard>

            <DashboardCard title="Top Recurring Hazards" subtitle="Most frequent across the corpus" icon={ListChecks} iconColor="#2563eb" className="xl:col-span-3">
              <ul className="space-y-1.5">
                {data.topHazards.slice(0, 7).map((hazard) => (
                  <li key={hazard.name} className="flex items-center gap-3">
                    <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{hazard.name}</span>
                    <div className="h-1.5 w-28 overflow-hidden rounded-full bg-black/[0.06]">
                      <div className="h-full rounded-full bg-brand" style={{ width: `${hazard.percentage ?? 0}%` }} />
                    </div>
                    <span className="w-14 shrink-0 text-right font-mono text-[11px] text-fg-muted">
                      {hazard.count} · {hazard.percentage}%
                    </span>
                  </li>
                ))}
              </ul>
            </DashboardCard>
          </div>

          <div className="grid gap-4 xl:grid-cols-5">
            <DashboardCard title="High-Risk Locations" subtitle="Ranked by high-risk report count, not volume" icon={MapPin} iconColor="#2563eb" className="xl:col-span-2">
              <ul className="space-y-1.5">
                {data.highRiskLocations.slice(0, 6).map((location) => (
                  <li key={location.location} className="flex items-baseline justify-between gap-3 rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2">
                    <span className="min-w-0 truncate text-[13px] text-fg">{location.location}</span>
                    <span className="shrink-0 font-mono text-[11px] text-fg-muted">
                      {location.highRiskCount} high / {location.count}
                    </span>
                  </li>
                ))}
              </ul>
            </DashboardCard>

            <DashboardCard
              title="Recent Reports"
              subtitle="Most recently analysed"
              icon={ListChecks}
              iconColor="#2563eb"
              className="xl:col-span-3"
              actions={<Button size="sm" variant="ghost" icon={RefreshCw} loading={busy} onClick={() => void load()}>Refresh</Button>}
            >
              <ul className="space-y-1.5">
                {data.recentReports.slice(0, 6).map((report) => (
                  <li key={report.id} className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg">
                        {report.summary || report.reportText.slice(0, 90)}
                      </span>
                      {report.riskLevel && <RiskBadge level={toDisplayRisk(report.riskLevel)} size="sm" />}
                    </div>
                    <p className="mt-0.5 text-[10.5px] text-fg-subtle">
                      #{report.id} · {report.location ?? 'location not stated'} · {report.source}
                    </p>
                  </li>
                ))}
              </ul>
            </DashboardCard>
          </div>

          <p className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-4 py-3 text-[11px] leading-relaxed text-fg-subtle">
            {data.disclaimer} {data.syntheticNotice}
            {data.llmAvailable
              ? ` Narrative generated by ${data.llmModel}; all risk levels and counts are deterministic.`
              : ' Language model unavailable — narrative text is rule-generated; classifications are unaffected.'}
          </p>
        </>
      )}
    </div>
  );
}
