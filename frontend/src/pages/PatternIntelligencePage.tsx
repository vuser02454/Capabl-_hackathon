/**
 * Pattern Intelligence — cross-report analysis, which is where a precursor detector earns its name.
 *
 * Every count on this page is computed deterministically from the stored corpus. The language
 * model is handed the finished table and asked only what the distribution implies; it never
 * produces a number, so it cannot get one wrong. The `narrativeSource` badge says which of the two
 * wrote the prose.
 */
import { Building2, Layers, ListChecks, MapPin, RefreshCw, TrendingUp } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { DataModeBadge } from '../components/ui/DataModeBadge';
import { useSettings } from '../context/SettingsContext';
import type { CountedItem, SafetyPatterns } from '../types/safety';

const SERIES = ['#2563eb', '#7c3aed', '#0891b2', '#d97706', '#059669', '#dc2626', '#4f46e5'];

function RankedList({ items, labelKey }: { items: CountedItem[]; labelKey: keyof CountedItem }) {
  if (!items.length) return <p className="text-xs text-fg-subtle">Nothing recorded yet.</p>;
  const max = Math.max(...items.map((i) => i.count));
  return (
    <ul className="space-y-1.5">
      {items.map((item, index) => (
        <li key={index} className="flex items-center gap-3">
          <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{String(item[labelKey])}</span>
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-black/[0.06]">
            <div className="h-full rounded-full bg-brand" style={{ width: `${(100 * item.count) / max}%` }} />
          </div>
          <span className="w-8 shrink-0 text-right font-mono text-[11px] text-fg-muted">{item.count}</span>
        </li>
      ))}
    </ul>
  );
}

export function PatternIntelligencePage() {
  const { api } = useSettings();
  const [data, setData] = useState<SafetyPatterns | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await api.safetyPatterns(true));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load pattern analysis.');
    } finally {
      setBusy(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <DashboardCard title="Pattern Intelligence" subtitle="Unavailable" icon={TrendingUp} iconColor="#dc2626">
        <p className="text-sm text-fg-muted">{error}</p>
        <Button className="mt-3" size="sm" variant="ghost" icon={RefreshCw} onClick={() => void load()}>Retry</Button>
      </DashboardCard>
    );
  }
  if (!data) {
    return (
      <DashboardCard title="Pattern Intelligence" subtitle="Analysing corpus…" icon={TrendingUp} iconColor="#2563eb">
        <div className="skeleton h-24 w-full" />
      </DashboardCard>
    );
  }

  const incidentData = data.incidentTypes.slice(0, 6).map((item) => ({
    name: item.type ?? 'Unknown', value: item.count,
  }));
  const locationData = data.highRiskLocations.slice(0, 7).map((item) => ({
    name: item.location ?? '—', high: item.highRiskCount ?? 0, total: item.count,
  }));

  return (
    <div className="space-y-4">
      <DashboardCard
        title="Cross-Report Trend"
        subtitle={`${data.reportCount} reports analysed together`}
        icon={TrendingUp}
        iconColor="#2563eb"
        actions={
          <div className="flex items-center gap-2">
            <DataModeBadge
              tone={data.narrativeSource === 'llm' ? 'live' : 'historical'}
              label={data.narrativeSource === 'llm' ? 'LLM interpretation' : 'Rule-generated'}
              size="sm"
            />
            <Button size="sm" variant="ghost" icon={RefreshCw} loading={busy} onClick={() => void load()}>
              Refresh
            </Button>
          </div>
        }
      >
        <p className="text-[13px] leading-relaxed text-fg-muted">{data.trendSummary}</p>
        {data.emergingPatterns.length > 0 && (
          <ul className="mt-3 space-y-2">
            {data.emergingPatterns.map((pattern, index) => (
              <li key={index} className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-[13px] font-medium text-fg">{pattern.pattern}</span>
                  {pattern.count !== null && (
                    <span className="shrink-0 font-mono text-[11px] text-fg-muted">×{pattern.count}</span>
                  )}
                </div>
                {pattern.detail && <p className="mt-0.5 text-xs text-fg-muted">{pattern.detail}</p>}
                <p className="mt-1 text-[10px] text-fg-subtle">Evidence: {pattern.evidence}</p>
              </li>
            ))}
          </ul>
        )}
      </DashboardCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <DashboardCard title="Top Recurring Hazards" subtitle="Counted across every report" icon={ListChecks} iconColor="#2563eb">
          <RankedList items={data.topHazards.slice(0, 8)} labelKey="name" />
        </DashboardCard>
        <DashboardCard title="Top Risk Factors" subtitle="Hazards plus absent controls and conditions" icon={Layers} iconColor="#2563eb">
          <RankedList items={data.topRiskFactors.slice(0, 8)} labelKey="name" />
        </DashboardCard>
      </div>

      <DashboardCard title="High-Risk Locations" subtitle="Dark bar = reports classified HIGH at that location" icon={MapPin} iconColor="#2563eb">
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={locationData} margin={{ left: 4, right: 16, bottom: 40 }}>
              <XAxis dataKey="name" angle={-28} textAnchor="end" interval={0} height={60}
                     tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: 'currentColor' }}
                     className="text-fg-subtle" />
              <YAxis allowDecimals={false} tickLine={false} axisLine={false}
                     tick={{ fontSize: 11, fill: 'currentColor' }} className="text-fg-subtle" />
              <Tooltip cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
              <Bar dataKey="total" fill="#c7d2fe" radius={[5, 5, 0, 0]} barSize={22} name="All reports" />
              <Bar dataKey="high" fill="#dc2626" radius={[5, 5, 0, 0]} barSize={22} name="High risk" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </DashboardCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <DashboardCard title="Incident Types" subtitle="Distribution across the corpus" icon={Layers} iconColor="#2563eb">
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={incidentData} dataKey="value" nameKey="name" innerRadius={48} outerRadius={82} paddingAngle={2}>
                  {incidentData.map((entry, index) => (
                    <Cell key={entry.name} fill={SERIES[index % SERIES.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {incidentData.map((entry, index) => (
              <li key={entry.name} className="flex items-center gap-1.5 text-[11px] text-fg-muted">
                <span className="size-2 rounded-full" style={{ background: SERIES[index % SERIES.length] }} />
                {entry.name} · {entry.value}
              </li>
            ))}
          </ul>
        </DashboardCard>

        <div className="space-y-4">
          <DashboardCard title="Departments" subtitle="Where reports originate" icon={Building2} iconColor="#2563eb">
            <RankedList items={data.topDepartments.slice(0, 6)} labelKey="department" />
          </DashboardCard>
          <DashboardCard title="Recurring Root Causes" subtitle="Extracted per report, counted here" icon={ListChecks} iconColor="#2563eb">
            <RankedList items={data.recurringCauses.slice(0, 5)} labelKey="cause" />
          </DashboardCard>
        </div>
      </div>

      <p className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-4 py-3 text-[11px] leading-relaxed text-fg-subtle">
        {data.syntheticNotice} All counts on this page are computed deterministically from the stored
        corpus; the language model only interprets the resulting distribution.
      </p>
    </div>
  );
}
