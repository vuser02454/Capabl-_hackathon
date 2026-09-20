/**
 * Admin Safety Map — the human-review surface.
 *
 * The AI never declares an area dangerous. It produces a CANDIDATE with the evidence attached, and
 * everything downstream of that is a human action taken here. The review panel therefore leads
 * with the supporting reports rather than the verdict: the admin is being asked to check a claim,
 * not to rubber-stamp one.
 *
 * AI-detected candidates and admin-flagged locations are labelled distinctly throughout, because
 * conflating "three workers reported this" with "I flagged this" would misrepresent the evidence.
 */
import { Crosshair, Flag, MapPin, PlusCircle, RefreshCw, ShieldAlert, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { PlaceSearch } from '../components/safety/PlaceSearch';
import { SafetyMap, type MapMarker } from '../components/safety/SafetyMap';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { DataModeBadge } from '../components/ui/DataModeBadge';
import { Chip } from '../components/ui/primitives';
import { RiskBadge } from '../components/ui/RiskBadge';
import { useSettings } from '../context/SettingsContext';
import { useGeolocation } from '../hooks/useGeolocation';
import { toDisplayRisk, type AdminMapData, type SafetyHotspot, type SupportingReport } from '../types/safety';

const DEFAULT_CENTER: [number, number] = [12.9716, 77.5946];

const STATUS_TONE: Record<string, string> = {
  PENDING_REVIEW: 'border-risk-high/25 bg-risk-high/10 text-risk-high',
  ACKNOWLEDGED: 'border-risk-moderate/25 bg-risk-moderate/10 text-risk-moderate',
  INVESTIGATING: 'border-risk-moderate/25 bg-risk-moderate/10 text-risk-moderate',
  PUBLISHED: 'border-info/25 bg-info/10 text-info',
  RESOLVED: 'border-risk-low/25 bg-risk-low/10 text-risk-low',
  DISMISSED: 'border-black/10 bg-black/[0.04] text-fg-subtle',
};

const ACTIONS: Array<{ id: string; label: string }> = [
  { id: 'acknowledge', label: 'Acknowledge' },
  { id: 'investigate', label: 'Investigate' },
  { id: 'resolve', label: 'Resolve' },
  { id: 'dismiss', label: 'Dismiss' },
];

export function AdminMapPage() {
  const { api } = useSettings();
  const { fix, locate, status: geoStatus } = useGeolocation();
  const [data, setData] = useState<AdminMapData | null>(null);
  const [selected, setSelected] = useState<SafetyHotspot | null>(null);
  const [supporting, setSupporting] = useState<SupportingReport[]>([]);
  const [searchCenter, setSearchCenter] = useState<[number, number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Manual Flagging State
  const [flagModalOpen, setFlagModalOpen] = useState(false);
  const [flagPicking, setFlagPicking] = useState(false);
  const [flagLat, setFlagLat] = useState<number | ''>('');
  const [flagLon, setFlagLon] = useState<number | ''>('');
  const [flagReason, setFlagReason] = useState('');
  const [flagLocationText, setFlagLocationText] = useState('');
  const [flagSeverity, setFlagSeverity] = useState('MEDIUM');
  const [flagRadius, setFlagRadius] = useState(1000);

  const load = useCallback(async () => {
    try {
      setData(await api.adminMap());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load the safety map.');
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  const openHotspot = async (hotspot: SafetyHotspot) => {
    setSelected(hotspot);
    setSupporting([]);
    try {
      setSupporting((await api.adminHotspotDetail(hotspot.id)).supportingReports);
    } catch {
      /* the panel still works without the supporting list */
    }
  };

  const act = async (action: string) => {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await api.adminHotspotAction(selected.id, action);
      setSelected(updated.hotspot);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Could not ${action} the hotspot.`);
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await api.adminPublishAnnouncement({
        title: `Safety Alert — ${selected.locations[0] ?? selected.primaryHazard ?? 'Flagged location'}`,
        message:
          `${selected.primaryHazard ?? 'A hazard'} has been reported in this area. ` +
          `Please avoid the marked area until the safety team completes inspection.`,
        severity: selected.riskLevel,
        hotspotId: selected.id,
        latitude: selected.latitude,
        longitude: selected.longitude,
        locationText: selected.locations[0] ?? null,
      });
      await load();
      const refreshed = await api.adminHotspotDetail(selected.id);
      setSelected(refreshed.hotspot);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not publish the alert.');
    } finally {
      setBusy(false);
    }
  };

  const submitFlag = async (e: React.FormEvent) => {
    e.preventDefault();
    if (flagLat === '' || flagLon === '' || !flagReason.trim()) {
      setError('Please provide latitude, longitude, and hazard description.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.adminFlagHotspot({
        latitude: Number(flagLat),
        longitude: Number(flagLon),
        reason: flagReason.trim(),
        severity: flagSeverity,
        radius_meters: flagRadius,
        location_text: flagLocationText.trim() || undefined,
      });
      setFlagModalOpen(false);
      setFlagPicking(false);
      setFlagReason('');
      setFlagLocationText('');
      await load();
      if (res.hotspot) {
        setSelected(res.hotspot);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to flag location.');
    } finally {
      setBusy(false);
    }
  };

  const markers: MapMarker[] = useMemo(() => {
    if (!data) return [];
    const out: MapMarker[] = data.reports.map((report) => ({
      id: `r${report.id}`, latitude: report.latitude, longitude: report.longitude,
      kind: 'report', title: `Report #${report.id}`,
      body: `${report.hazards.join(', ') || 'No hazard detected'} · ${report.riskLevel ?? '—'}`,
    }));
    for (const hotspot of data.hotspots) {
      const kind = hotspot.status === 'RESOLVED' ? 'resolved'
        : hotspot.status === 'INVESTIGATING' ? 'investigating'
        : hotspot.status === 'PUBLISHED' ? 'published' : 'candidate';
      out.push({
        id: `h${hotspot.id}`, latitude: hotspot.latitude, longitude: hotspot.longitude,
        kind, radiusMeters: hotspot.radiusMeters,
        title: `${hotspot.isAiDetected ? 'AI candidate' : 'Admin flagged'}: ${hotspot.primaryHazard ?? 'Hazard'}`,
        body: `${hotspot.reportCount} related reports · ${hotspot.status}`,
        onSelect: () => void openHotspot(hotspot),
      });
    }
    if (flagModalOpen && typeof flagLat === 'number' && typeof flagLon === 'number') {
      out.push({
        id: 'flag-preview',
        latitude: flagLat,
        longitude: flagLon,
        kind: 'investigating',
        title: 'Flagged Location Preview',
        radiusMeters: flagRadius,
      });
    }
    if (fix) out.push({ id: 'me', latitude: fix.latitude, longitude: fix.longitude, kind: 'me', title: 'You are here' });
    return out;
  }, [data, fix, flagModalOpen, flagLat, flagLon, flagRadius]);

  const center: [number, number] = fix ? [fix.latitude, fix.longitude]
    : data?.hotspots.length ? [data.hotspots[0].latitude, data.hotspots[0].longitude]
    : DEFAULT_CENTER;

  return (
    <div className="space-y-4">
      <DashboardCard
        title="Safety Map"
        subtitle={data?.rule.summary ?? 'Reports, candidate hotspots and published alerts'}
        icon={MapPin}
        iconColor="#2563eb"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-64">
              <PlaceSearch
                label="Search location"
                placeholder="Search location in India..."
                onChoose={(choice) => {
                  setSearchCenter([choice.latitude, choice.longitude]);
                  if (flagModalOpen) {
                    setFlagLat(Number(choice.latitude.toFixed(6)));
                    setFlagLon(Number(choice.longitude.toFixed(6)));
                    if (!flagLocationText) setFlagLocationText(choice.label);
                  }
                  setError(null);
                }}
              />
            </div>
            <Button
              size="sm"
              variant={flagModalOpen ? 'primary' : 'ghost'}
              icon={PlusCircle}
              onClick={() => {
                setFlagModalOpen(!flagModalOpen);
                if (!flagModalOpen && searchCenter) {
                  setFlagLat(Number(searchCenter[0].toFixed(6)));
                  setFlagLon(Number(searchCenter[1].toFixed(6)));
                }
              }}
            >
              Flag Location
            </Button>
            <Button size="sm" variant="ghost" icon={Crosshair} loading={geoStatus === 'locating'} onClick={locate}>
              Find My Location
            </Button>
            <Button size="sm" variant="ghost" icon={RefreshCw} onClick={() => void load()}>Refresh</Button>
          </div>
        }
      >
        {error && <p className="mb-2 rounded-lg border border-risk-high/25 bg-risk-high/[0.07] px-3 py-2 text-xs text-risk-high">{error}</p>}

        {flagModalOpen && (
          <form onSubmit={submitFlag} className="mb-4 rounded-xl border border-brand/20 bg-brand/[0.03] p-3.5 space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-fg flex items-center gap-1.5">
                <Flag className="size-3.5 text-brand" /> Manually Flag Safety Hotspot
              </h4>
              <button
                type="button"
                onClick={() => { setFlagModalOpen(false); setFlagPicking(false); }}
                className="text-fg-subtle hover:text-fg"
              >
                <X className="size-4" />
              </button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4 text-xs">
              <div>
                <label className="block mb-1 text-[11px] font-medium text-fg-subtle">Latitude</label>
                <input
                  type="number"
                  step="any"
                  required
                  value={flagLat}
                  onChange={(e) => setFlagLat(e.target.value === '' ? '' : parseFloat(e.target.value))}
                  placeholder="12.9716"
                  className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-fg"
                />
              </div>
              <div>
                <label className="block mb-1 text-[11px] font-medium text-fg-subtle">Longitude</label>
                <input
                  type="number"
                  step="any"
                  required
                  value={flagLon}
                  onChange={(e) => setFlagLon(e.target.value === '' ? '' : parseFloat(e.target.value))}
                  placeholder="77.5946"
                  className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-fg"
                />
              </div>
              <div>
                <label className="block mb-1 text-[11px] font-medium text-fg-subtle">Severity</label>
                <select
                  value={flagSeverity}
                  onChange={(e) => setFlagSeverity(e.target.value)}
                  className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-fg"
                >
                  <option value="LOW">Low</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="HIGH">High</option>
                  <option value="CRITICAL">Critical</option>
                </select>
              </div>
              <div>
                <label className="block mb-1 text-[11px] font-medium text-fg-subtle">Radius (meters)</label>
                <input
                  type="number"
                  min="50"
                  max="5000"
                  value={flagRadius}
                  onChange={(e) => setFlagRadius(parseInt(e.target.value, 10) || 1000)}
                  className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-fg"
                />
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 text-xs">
              <div>
                <label className="block mb-1 text-[11px] font-medium text-fg-subtle">Location Name / Area</label>
                <input
                  type="text"
                  value={flagLocationText}
                  onChange={(e) => setFlagLocationText(e.target.value)}
                  placeholder="e.g. Loading Bay 3, Warehouse East"
                  className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-fg"
                />
              </div>
              <div>
                <label className="block mb-1 text-[11px] font-medium text-fg-subtle">Hazard / Reason *</label>
                <input
                  type="text"
                  required
                  value={flagReason}
                  onChange={(e) => setFlagReason(e.target.value)}
                  placeholder="e.g. Chemical spill risk, active heavy equipment route"
                  className="w-full rounded-lg border border-black/[0.1] bg-white px-2.5 py-1.5 text-xs text-fg"
                />
              </div>
            </div>

            <div className="flex items-center justify-between pt-1">
              <Button
                type="button"
                size="sm"
                variant={flagPicking ? 'primary' : 'ghost'}
                onClick={() => setFlagPicking(!flagPicking)}
              >
                {flagPicking ? 'Click map to set coordinates…' : 'Pick Coordinates on Map'}
              </Button>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => { setFlagModalOpen(false); setFlagPicking(false); }}
                >
                  Cancel
                </Button>
                <Button type="submit" size="sm" variant="primary" loading={busy}>
                  Create Flagged Hotspot
                </Button>
              </div>
            </div>
          </form>
        )}

        <SafetyMap
          markers={markers}
          center={center}
          zoom={14}
          height={460}
          recenterTo={searchCenter ?? (fix ? [fix.latitude, fix.longitude] : null)}
          onPick={flagPicking ? (lat, lng) => {
            setFlagLat(Number(lat.toFixed(6)));
            setFlagLon(Number(lng.toFixed(6)));
          } : undefined}
        />
        <p className="mt-2 text-[11px] text-fg-subtle">
          Finding your location only moves the map — it does not flag anything.{' '}
          {data?.rule.disclaimer}
        </p>
      </DashboardCard>

      {selected && (
        <DashboardCard
          title={selected.isAiDetected ? 'AI-Detected Candidate Hotspot' : 'Admin-Flagged Location'}
          subtitle={selected.explanation ?? ''}
          icon={selected.isAiDetected ? ShieldAlert : Flag}
          iconColor={selected.isAiDetected ? '#dc2626' : '#d97706'}
          actions={
            <div className="flex items-center gap-2">
              <DataModeBadge tone={selected.isAiDetected ? 'live' : 'historical'}
                             label={selected.isAiDetected ? 'AI detected' : 'Admin flagged'} size="sm" />
              <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-wider uppercase ${STATUS_TONE[selected.status] ?? ''}`}>
                {selected.status.replace('_', ' ')}
              </span>
            </div>
          }
        >
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <RiskBadge level={toDisplayRisk(selected.riskLevel)} suffix="RISK" size="md" />
                <span className="text-[13px] text-fg">{selected.primaryHazard}</span>
              </div>
              <p className="text-xs text-fg-muted">
                {selected.reportCount} related reports within {selected.radiusMeters} m
                {selected.locations.length > 0 && ` · ${selected.locations.join(', ')}`}
              </p>
              {selected.relatedHazards.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {selected.relatedHazards.map((hazard) => <Chip key={hazard}>{hazard}</Chip>)}
                </div>
              )}
              {selected.reportIds.length > 0 && (
                <p className="font-mono text-[10.5px] text-fg-subtle">
                  Supporting: {selected.reportIds.map((id) => `SR-${id}`).join(', ')}
                </p>
              )}
            </div>

            <div>
              <p className="eyebrow mb-1.5">Supporting reports</p>
              {supporting.length === 0 ? (
                <p className="text-xs text-fg-subtle">
                  {selected.isAiDetected ? 'Loading…' : 'None — this location was flagged manually, not derived from reports.'}
                </p>
              ) : (
                <ul className="max-h-40 space-y-1.5 overflow-y-auto pr-1">
                  {supporting.map((report) => (
                    <li key={report.id} className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-2.5 py-2">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-mono text-[10px] text-fg-subtle">SR-{report.id}</span>
                        {report.riskLevel && <RiskBadge level={toDisplayRisk(report.riskLevel)} size="sm" />}
                      </div>
                      <p className="mt-0.5 text-[11.5px] leading-relaxed text-fg-muted">{report.reportText}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2 border-t border-black/[0.06] pt-3">
            {ACTIONS.map((action) => (
              <Button key={action.id} size="sm" variant="ghost" disabled={busy}
                      onClick={() => void act(action.id)}>
                {action.label}
              </Button>
            ))}
            <Button size="sm" variant="primary" disabled={busy || selected.status === 'PUBLISHED'}
                    onClick={() => void publish()}>
              {selected.status === 'PUBLISHED' ? 'Alert published ✓' : 'Publish Alert'}
            </Button>
          </div>
          <p className="mt-2 text-[10.5px] leading-relaxed text-fg-subtle">
            Publishing makes this visible to every worker on their Safety Map. Nothing reaches
            workers until you publish it.
          </p>
        </DashboardCard>
      )}
    </div>
  );
}
