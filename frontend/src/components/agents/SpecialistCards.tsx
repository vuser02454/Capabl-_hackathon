import { TriangleAlert, ArrowUpRight, ImageUp, Radio } from 'lucide-react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useNavigation } from '../../context/NavigationContext';
import { formatTime, relativeTime } from '../../lib/format';
import { waterProvenance } from '../../lib/waterSource';
import { Sparkline } from '../charts/TrendChart';
import { Button } from '../ui/Button';
import { DataModeBadge } from '../ui/DataModeBadge';
import { MetricCard } from '../ui/MetricCard';
import { Chip } from '../ui/primitives';
import { AgentCard } from './AgentCard';
import { AGENT_META } from './agentMeta';
import { CategoryBreakdown, DetectionViewer } from './DetectionViewer';

export function AirAgentCard({ delay }: { delay?: number }) {
  const { display, pending, failures, environment } = useAnalysis();
  const { navigate } = useNavigation();
  const air = display.air;
  const series = (environment?.history['24h'] ?? []).map((point) => ({ label: formatTime(point.timestamp), value: point.pm25 }));

  return (
    <AgentCard
      agent="air"
      result={air}
      pending={pending.air}
      failure={failures.air}
      delay={delay}
      subtitle={air?.stationName ?? 'Nearest monitoring station'}
      badges={
        air && !air.isMock ? (
          <Chip color="#059669" icon={<Radio className="size-3 text-risk-low" />}>
            Live · {air.dataSource}
          </Chip>
        ) : undefined
      }
      footerNote={
        air
          ? `${air.stationDistanceKm != null ? `${air.stationDistanceKm.toFixed(1)} km away` : air.stationId} · updated ${formatTime(air.timestamp)}`
          : undefined
      }
      actions={
        <Button size="sm" iconRight={ArrowUpRight} onClick={() => navigate('air')}>
          View Analysis
        </Button>
      }
    >
      {air && (
        <>
          <div className="grid grid-cols-2 gap-2">
            {air.measurements.map((m) => (
              <MetricCard key={m.key} label={m.label} value={m.value} unit={m.unit} status={m.status} progress={m.subScore} />
            ))}
          </div>
          <div className="mt-3 rounded-xl border border-black/[0.05] bg-black/[0.015] px-3 pt-2.5 pb-1">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-fg-subtle">PM2.5 · last 24h</span>
              <span className="text-fg-subtle">
                AQI <span className="font-semibold text-fg">{air.aqi ?? '—'}</span> {air.aqiCategory}
              </span>
            </div>
            <Sparkline data={series} color={AGENT_META.air.color} unit="µg/m³" series="PM2.5" />
          </div>
          {air.anomalies[0] && (
            <p className="mt-2.5 flex items-center gap-1.5 text-[11px] text-risk-moderate">
              <TriangleAlert className="size-3.5 shrink-0" />
              Anomaly: {air.anomalies[0]}
            </p>
          )}
        </>
      )}
    </AgentCard>
  );
}

export function WaterAgentCard({ delay }: { delay?: number }) {
  const { display, pending, failures } = useAnalysis();
  const { navigate } = useNavigation();
  const water = display.water;
  const degraded = water?.sensorStatus !== 'online';
  const provenance = water ? waterProvenance(water) : null;

  return (
    <AgentCard
      agent="water"
      result={water}
      pending={pending.water}
      failure={failures.water}
      delay={delay}
      subtitle={water?.sensorName ?? 'IoT water sensor'}
      badges={
        <>
          {provenance && <DataModeBadge tone={provenance.tone} label={provenance.label} />}
          {water && (
            <Chip color={degraded ? '#d97706' : '#059669'} icon={<Radio className="size-3" style={{ color: degraded ? '#d97706' : '#059669' }} />}>
              Sensor {water.sensorStatus}
            </Chip>
          )}
        </>
      }
      footerNote={water ? `Last updated ${relativeTime(water.timestamp)}` : undefined}
      actions={
        <Button size="sm" iconRight={ArrowUpRight} onClick={() => navigate('water')}>
          View Analysis
        </Button>
      }
    >
      {water && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {water.measurements.map((m) => (
              <MetricCard key={m.key} label={m.key === 'temperature' ? 'Temp' : m.label} value={m.value} unit={m.unit} status={m.status} progress={m.subScore} />
            ))}
          </div>
          <dl className="mt-3 space-y-2 rounded-xl border border-black/[0.05] bg-black/[0.015] p-3 text-xs">
            <div className="flex justify-between gap-3">
              <dt className="text-fg-subtle">Sensor ID</dt>
              <dd className="font-mono text-fg-muted">{water.sensorId}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-fg-subtle">Validation</dt>
              <dd className="text-fg-muted">
                {water.measurements.length - water.warnings.length}/{water.measurements.length} readings valid
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-fg-subtle">Data source</dt>
              <dd className="truncate text-fg-muted" title={provenance?.description}>
                {water.dataSource}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-fg-subtle">Confidence</dt>
              <dd className="text-fg-muted tabular">{Math.round(water.confidence * 100)}%</dd>
            </div>
          </dl>
          {provenance && !provenance.isLive && (
            <p className="mt-2 flex items-center gap-1.5 text-[11px] text-fg-subtle">
              <TriangleAlert className="size-3.5 shrink-0 text-risk-moderate" />
              Not a live sensor reading — {provenance.description}
            </p>
          )}
          {water.warnings.map((warning) => (
            <p key={warning} className="mt-2 flex items-center gap-1.5 text-[11px] text-risk-moderate">
              <TriangleAlert className="size-3.5 shrink-0" />
              {warning}
            </p>
          ))}
        </>
      )}
    </AgentCard>
  );
}

export function WasteAgentCard({ delay }: { delay?: number }) {
  const { display, pending, failures } = useAnalysis();
  const { navigate } = useNavigation();
  const waste = display.waste;

  return (
    <AgentCard
      agent="waste"
      result={waste}
      pending={pending.waste}
      failure={failures.waste}
      delay={delay}
      subtitle={waste?.sourceName ?? 'Camera observation point'}
      footerNote={waste ? `${waste.inputType === 'upload' ? 'Uploaded image' : waste.sourceId} · ${formatTime(waste.timestamp)}` : undefined}
      actions={
        <>
          {/* Uploading here used to run the demo provider, which drew random boxes over the
              user's own photo. Real detection lives on the waste page; send them there. */}
          <Button size="sm" icon={ImageUp} onClick={() => navigate('waste')}>
            Analyze Image
          </Button>
          <Button size="sm" variant="ghost" onClick={() => navigate('waste')} aria-label="View waste analysis">
            <ArrowUpRight className="size-3.5" />
          </Button>
        </>
      }
    >
      {waste && (
        <>
          {/* The label was hardcoded to "YOLOv8n", naming a model that never ran on this
              data. `waste.model` carries the provider's own name, including "(simulated)". */}
          <DetectionViewer
            detections={waste.detections}
            imageUrl={null}
            sourceLabel={waste.sourceId}
            model={waste.model}
            scanning={pending.waste}
            maxLabels={4}
          />
          <div className="mt-3 flex items-baseline justify-between">
            <p className="text-xs text-fg-subtle">
              Detected <span className="text-base font-semibold text-fg">{waste.totalObjects}</span> objects
            </p>
            <p className="text-[11px] text-fg-subtle">
              Density index <span className="text-fg-muted tabular">{waste.densityIndex.toFixed(2)}</span>
            </p>
          </div>
          <CategoryBreakdown counts={waste.counts} className="mt-2" />
        </>
      )}
    </AgentCard>
  );
}
