import { ArrowUpRight, Bug, Camera, Gauge, MapPinOff, Radio, ScanSearch, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import { AgentDetailLayout, MeasurementTable } from '../components/agents/AgentDetails';
import { AGENT_META, WASTE_CATEGORY_COLORS } from '../components/agents/agentMeta';
import { CategoryBreakdown, DetectionViewer } from '../components/agents/DetectionViewer';
import { RealWasteDetection } from '../components/agents/RealWasteDetection';
import { WasteDebugPanel } from '../components/agents/WasteDebugPanel';
import { WaterFrameInvestigation } from '../components/agents/WaterFrameInvestigation';
import { WaterImageInput } from '../components/agents/WaterImageInput';
import { WaterVisionPanel } from '../components/agents/WaterVisionPanel';
import { ParameterRadar } from '../components/charts/ParameterRadar';
import { TrendChart } from '../components/charts/TrendChart';
import { RANGE_OPTIONS, seriesChange, seriesFor } from '../components/charts/TrendsSection';
import { PollutantDetailCard } from '../components/agents/PollutantDetailCard';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { DataModeBadge } from '../components/ui/DataModeBadge';
import { SegmentedControl } from '../components/ui/primitives';
import { useAnalysis } from '../context/AnalysisContext';
import { pct, RANGE_LABELS, relativeTime } from '../lib/format';
import { waterProvenance } from '../lib/waterSource';
import type { TrendRange } from '../types/environment';

const POLLUTANT_LABELS: Record<string, string> = { pm25: 'PM2.5', pm10: 'PM10', no2: 'NO₂', o3: 'O₃' };

function useRange() {
  const [range, setRange] = useState<TrendRange>('24h');
  const control = (id: string) => <SegmentedControl ariaLabel="Time range" layoutId={`range-${id}`} options={RANGE_OPTIONS} value={range} onChange={setRange} />;
  return { range, control };
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
      <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">{label}</p>
      <p className="mt-1 text-lg font-semibold text-fg">{value}</p>
      {hint && <p className="text-[10.5px] text-fg-subtle">{hint}</p>}
    </div>
  );
}

export function AirAgentPage() {
  const { display, environment, state } = useAnalysis();
  const { range, control } = useRange();
  const air = display.air;
  const history = environment?.history[range] ?? [];

  return (
    <AgentDetailLayout agent="air">
      {air && (
        <div className="space-y-6">
          <div className="grid gap-4 xl:grid-cols-5">
            <DashboardCard title="Pollutant measurements" subtitle={`${air.stationName} · normalized against WHO guidelines`} icon={Gauge} iconColor={AGENT_META.air.color} className="xl:col-span-3">
              <MeasurementTable measurements={air.measurements} />
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat label="India NAQI" value={air.aqi === null ? '—' : String(air.aqi)} hint={air.aqiCategory ?? undefined} />
                <Stat label="Dominant" value={air.dominantPollutant ?? '—'} hint="Highest sub-index" />
                <Stat
                  label="Station"
                  value={air.isMock ? air.stationId : air.stationId.replace('OPENAQ-', '#')}
                  hint={`${air.stationDistanceKm != null ? `${air.stationDistanceKm.toFixed(1)} km · ` : ''}${air.referenceGrade === false ? 'Low-cost sensor' : 'Reference grade'}`}
                />
                <Stat label="Anomalies" value={String(air.anomalies.length)} hint="vs 24-h baseline" />
              </div>
              {air.sourceUrl && (
                <a href={air.sourceUrl} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs text-brand hover:underline">
                  View station on OpenAQ <ArrowUpRight className="size-3" />
                </a>
              )}
              {air.pollutantSources && Object.keys(air.pollutantSources).length > 0 && (
                <div className="mt-3 rounded-xl border border-black/[0.05] bg-black/[0.015] p-3">
                  <p className="eyebrow mb-1.5">Reading sources</p>
                  <ul className="space-y-1 text-xs">
                    {Object.entries(air.pollutantSources).map(([key, source]) => (
                      <li key={key} className="flex justify-between gap-3">
                        <span className="text-fg-subtle">{POLLUTANT_LABELS[key] ?? key}</span>
                        <span className="truncate text-right text-fg-muted">{source}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </DashboardCard>
            <TrendChart
              className="xl:col-span-2"
              title="PM2.5 Trend"
              icon={AGENT_META.air.icon}
              color={AGENT_META.air.color}
              unit="µg/m³"
              decimals={1}
              height={260}
              data={seriesFor(history, range, 'pm25')}
              rangeLabel={air.isMock ? RANGE_LABELS[range] : `${RANGE_LABELS[range]} · demo history`}
              threshold={{ value: 15, label: 'WHO guideline' }}
              current={air.pm25}
              change={seriesChange(history, 'pm25')}
              toolbar={control('air')}
            />
          </div>

          <PollutantDetailCard airResult={air} geographicContext={state.result?.geographicContext} />
        </div>
      )}
    </AgentDetailLayout>
  );
}

export function WaterAgentPage() {
  const { display, environment } = useAnalysis();
  const { range, control } = useRange();
  const water = display.water;
  const history = environment?.history[range] ?? [];
  const provenance = water ? waterProvenance(water) : null;

  return (
    <AgentDetailLayout agent="water">
      {/* The page leads with visual detection and the clicked-frame investigation. Measurements
          from the sensor/dataset chain still run and are reported further down as support. */}
      <WaterFrameInvestigation />

      {water && provenance && (
        <DashboardCard
            title="Data provenance"
            subtitle={provenance.description}
            icon={provenance.isLive ? Radio : MapPinOff}
            iconColor={provenance.color}
            actions={<DataModeBadge tone={provenance.tone} label={provenance.label} size="md" />}
          >
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Source" value={water.dataSource} />
              <Stat label="Sensor / site ID" value={water.sensorId} />
              <Stat label="Distance" value={water.sensorDistanceKm != null ? `${water.sensorDistanceKm.toFixed(1)} km` : '—'} hint="From analysis location" />
              <Stat label="Data age" value={water.dataAgeMinutes != null ? `${water.dataAgeMinutes} min` : '—'} />
            </div>
          </DashboardCard>
      )}

      {water && (
        <div className="grid gap-4 xl:grid-cols-5">
          {/* Supporting measurements, not the headline. This page leads with visual detection;
              the sensor/dataset chain still runs behind it and is reported here for completeness. */}
          <DashboardCard title="Supporting measurements" subtitle={`${water.sourceName ?? water.dataSource} · reference thresholds`} icon={Gauge} iconColor={AGENT_META.water.color} className="xl:col-span-3">
            <MeasurementTable measurements={water.measurements} />
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Sensor status" value={water.sensorStatus} hint={water.sensorStatus === 'online' ? 'All probes reporting' : 'Partial telemetry'} />
              <Stat
                label="Valid readings"
                value={`${water.measurements.length - water.warnings.length}/${water.measurements.length}`}
                hint="After validation"
              />
              <Stat label="Confidence" value={`${pct(water.confidence)}%`} hint={provenance?.label} />
              <Stat label="Last updated" value={relativeTime(water.timestamp)} />
            </div>
          </DashboardCard>
          <TrendChart
            className="xl:col-span-2"
            title="Water Turbidity Trend"
            icon={AGENT_META.water.icon}
            color={AGENT_META.water.color}
            unit="NTU"
            decimals={1}
            height={260}
            data={seriesFor(history, range, 'turbidity')}
            rangeLabel={RANGE_LABELS[range]}
            threshold={{ value: 5, label: 'BIS limit' }}
            current={water.turbidity}
            change={seriesChange(history, 'turbidity')}
            emptyMessage="The turbidity probe on this sensor is not reporting."
            toolbar={control('water')}
          />
        </div>
      )}

      {/* Camera / gallery input for the visual half of the evidence. */}
      {water && <WaterImageInput />}

      {/* Visual half of the Water Agent's evidence. Rendered only when the backend supplied it,
          so the in-browser demo engine (which has no vision stage) is unaffected. */}
      {water?.visualPollution && (
        <WaterVisionPanel
          vision={water.visualPollution}
          waterQualityScore={water.waterQualityScore}
          combinedScore={water.riskScore}
        />
      )}

      {water && (
        <DashboardCard
          title="Relative parameter profile"
          subtitle="Each axis is the agent's own normalized sub-score (0–100%) — for visual comparison only, not raw values or an independent risk score"
          icon={Gauge}
          iconColor={AGENT_META.water.color}
        >
          <ParameterRadar measurements={water.measurements} color={AGENT_META.water.color} />
        </DashboardCard>
      )}
    </AgentDetailLayout>
  );
}

export function WasteAgentPage() {
  const { display, pending, state, runAnalysis, environment } = useAnalysis();
  const { range, control } = useRange();
  const waste = display.waste;
  const running = state.phase === 'running';
  const history = environment?.history[range] ?? [];
  const [debugOpen, setDebugOpen] = useState(false);

  return (
    <AgentDetailLayout agent="waste">
      {/* The real models come first. Photographing litter is the thing a user actually wants to
          do here, and it must not land in the demo scenario below. */}
      <RealWasteDetection />

      {/* Temporary, while the source of the wrong labels is being located. */}
      {debugOpen ? (
        <WasteDebugPanel />
      ) : (
        <button
          type="button"
          onClick={() => setDebugOpen(true)}
          className="flex items-center gap-1.5 self-start rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 text-[11px] text-fg-subtle transition hover:bg-black/[0.05] hover:text-fg-muted"
        >
          <Bug className="size-3" /> Open pipeline debug
        </button>
      )}

      <div className="grid gap-4 xl:grid-cols-5">
        <DashboardCard
          title="Demo scenario"
          subtitle="Synthetic detections — not from a camera or an image"
          icon={ScanSearch}
          iconColor={AGENT_META.waste.color}
          className="xl:col-span-3"
          actions={
            <div className="flex items-center gap-2">
              <DataModeBadge tone="demo" label="Simulated" size="sm" />
              <Button size="sm" variant="ghost" icon={Camera} disabled={running} onClick={() => void runAnalysis()}>
                Re-run scenario
              </Button>
            </div>
          }
        >
          <div className="mb-3 flex items-start gap-2 rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-risk-moderate" />
            <p className="text-[11px] text-fg-muted">
              <span className="font-medium text-risk-moderate">Every box below is generated, not detected.</span>{' '}
              The demo provider invents labels, positions and confidences from a seeded random number
              generator and never looks at an image. Use <span className="text-fg">Real detection</span>{' '}
              above for an actual photo.
            </p>
          </div>
          {waste ? (
            <DetectionViewer
              detections={waste.detections}
              imageUrl={null}
              sourceLabel={waste.sourceId}
              model={waste.model}
              scanning={pending.waste}
              maxLabels={10}
            />
          ) : (
            <div className="skeleton aspect-[16/10] w-full rounded-xl" />
          )}
        </DashboardCard>

        <DashboardCard
          title="Scenario results"
          subtitle={waste ? `${waste.model}` : 'Waiting for the scenario'}
          icon={AGENT_META.waste.icon}
          iconColor={AGENT_META.waste.color}
          className="xl:col-span-2"
          actions={<DataModeBadge tone="demo" label="Simulated" size="sm" />}
        >
          {waste && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <Stat label="Detected objects" value={String(waste.totalObjects)} hint={waste.totalObjects >= 15 ? 'High density' : waste.totalObjects >= 8 ? 'Moderate density' : 'Low density'} />
                <Stat label="Density index" value={waste.densityIndex.toFixed(2)} hint="Objects per standard frame" />
              </div>
              <CategoryBreakdown counts={waste.counts} className="mt-4" />
              <div className="mt-4 max-h-64 overflow-auto rounded-xl border border-black/[0.05]">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-ink-850/95 backdrop-blur">
                    <tr className="text-[10.5px] tracking-wider text-fg-subtle uppercase">
                      <th className="px-3 py-2 font-medium">#</th>
                      <th className="px-3 py-2 font-medium">Object</th>
                      <th className="px-3 py-2 font-medium">Class</th>
                      <th className="px-3 py-2 text-right font-medium">Conf.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {waste.detections.map((detection) => (
                      <tr key={detection.id} className="border-t border-black/[0.04]">
                        <td className="px-3 py-1.5 font-mono text-[10.5px] text-fg-subtle">{detection.id.replace('det-', '')}</td>
                        <td className="px-3 py-1.5 text-fg">{detection.label}</td>
                        <td className="px-3 py-1.5">
                          <span className="inline-flex items-center gap-1.5 text-fg-muted capitalize">
                            <span className="size-2 rounded-sm" style={{ background: WASTE_CATEGORY_COLORS[detection.category] }} />
                            {detection.category}
                          </span>
                        </td>
                        <td className="px-3 py-1.5 text-right text-fg-muted tabular">{Math.round(detection.confidence * 100)}%</td>
                      </tr>
                    ))}
                    {waste.detections.length === 0 && (
                      <tr>
                        <td colSpan={4} className="px-3 py-6 text-center text-fg-subtle">
                          No objects detected
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </DashboardCard>
      </div>

      <TrendChart
        title="Waste Detection Count"
        icon={AGENT_META.waste.icon}
        color={AGENT_META.waste.color}
        unit="objects"
        variant="bar"
        height={220}
        data={seriesFor(history, range, 'wasteCount')}
        rangeLabel={RANGE_LABELS[range]}
        threshold={{ value: 15, label: 'High density' }}
        current={history[history.length - 1]?.wasteCount}
        change={seriesChange(history, 'wasteCount')}
        toolbar={control('waste')}
      />
    </AgentDetailLayout>
  );
}
