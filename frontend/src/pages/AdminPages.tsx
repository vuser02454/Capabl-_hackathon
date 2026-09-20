/**
 * The Safety Admin surfaces: dashboard, report list, review queue and published announcements.
 *
 * The admin is the decision-maker, so these screens are built to support a judgement rather than
 * to deliver a verdict. Candidate hotspots are labelled as candidates, AI-detected clusters are
 * kept visually distinct from locations an admin flagged by hand, and every count links back to
 * the report ids it came from.
 *
 * Nothing here publishes anything on its own. Publication is a button, pressed by a person.
 */
import {
  AlertTriangle, Bell, ClipboardList, FileText, Flag, Image as ImageIcon, MapPin, RefreshCw, ShieldAlert,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import {
  ActionTracker, ExplanationPanel, FeedbackControl, IncidentHistoryPanel, SpecializedResponsePanel,
} from '../components/safety/IncidentIntelligence';
import { SafetyChat } from '../components/safety/SafetyChat';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { DataModeBadge } from '../components/ui/DataModeBadge';
import { Chip } from '../components/ui/primitives';
import { RiskBadge } from '../components/ui/RiskBadge';
import { useNavigation } from '../context/NavigationContext';
import { useSettings } from '../context/SettingsContext';
import {
  toDisplayRisk,
  type AdminDashboard, type AdminReportDetail, type AdminReportRow,
  type HotspotDetail, type SafetyHotspot,
} from '../types/safety';

const STATUS_TONE: Record<string, string> = {
  PENDING_REVIEW: 'border-risk-high/25 bg-risk-high/10 text-risk-high',
  ACKNOWLEDGED: 'border-risk-moderate/25 bg-risk-moderate/10 text-risk-moderate',
  INVESTIGATING: 'border-risk-moderate/25 bg-risk-moderate/10 text-risk-moderate',
  PUBLISHED: 'border-info/25 bg-info/10 text-info',
  RESOLVED: 'border-risk-low/25 bg-risk-low/10 text-risk-low',
  DISMISSED: 'border-black/10 bg-black/[0.04] text-fg-subtle',
};

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold tracking-wider uppercase ${STATUS_TONE[status] ?? ''}`}>
      {status.replace('_', ' ')}
    </span>
  );
}

/** One headline number. Deliberately plain — these are counts, not measurements. */
function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
      <p className="text-[22px] leading-none font-semibold text-fg">{value}</p>
      <p className="mt-1 text-[11px] text-fg-muted">{label}</p>
      {hint && <p className="mt-0.5 text-[10px] text-fg-subtle">{hint}</p>}
    </div>
  );
}

// --- dashboard ------------------------------------------------------------------------------

export function AdminDashboardPage() {
  const { api } = useSettings();
  const { navigate } = useNavigation();
  const [data, setData] = useState<AdminDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.adminDashboard());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load the dashboard.');
    }
  }, [api]);
  useEffect(() => { void load(); }, [load]);

  if (error) return <p className="text-sm text-risk-high">{error}</p>;
  if (!data) return <p className="text-sm text-fg-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <DashboardCard
        title="Safety Overview" subtitle={data.rule.summary} icon={ShieldAlert} iconColor="#2563eb"
        actions={<Button size="sm" variant="ghost" icon={RefreshCw} onClick={() => void load()}>Refresh</Button>}
      >
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Reports" value={data.reportCount} />
          <Stat label="With a location" value={data.geolocatedCount} hint="geotagged in-app" />
          <Stat label="With a photo" value={data.photoCount} />
          <Stat label="Candidate hotspots" value={data.hotspotCount} />
          <Stat label="Awaiting review" value={data.pendingReview} hint="not visible to workers" />
          <Stat label="Published alerts" value={data.publishedAlertCount} />
        </div>

        {/* Worker safety activity, counted from stored route events. */}
        <div className="mt-2.5 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Workers" value={data.workerCount ?? 0} />
          <Stat label="Workers reporting" value={data.workersReportingIncidents ?? 0} />
          <Stat label="Route events" value={data.routeEventCount ?? 0} />
          <Stat label="Passed a hazard" value={data.workersPassingModerateHazards ?? 0} />
          <Stat label="Rerouted" value={data.workersReroutedFromHighHazards ?? 0}
                hint="high-severity alerts" />
          <Stat label="No safe route" value={data.noSafeAlternativeEvents ?? 0} />
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          <Chip>{data.riskBreakdown.HIGH} HIGH</Chip>
          <Chip>{data.riskBreakdown.MEDIUM} MEDIUM</Chip>
          <Chip>{data.riskBreakdown.LOW} LOW</Chip>
        </div>
        <p className="mt-2 text-[11px] text-fg-subtle">{data.rule.disclaimer}</p>
      </DashboardCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <DashboardCard title="Incident domains" subtitle="How reports route through the workflow"
                       icon={ClipboardList} iconColor="#7c3aed">
          <ul className="space-y-1.5">
            {data.domainBreakdown.map((item) => (
              <li key={item.domain} className="flex items-center gap-2">
                <span className="w-40 shrink-0 text-[12.5px] text-fg">{item.label}</span>
                <span className="h-1.5 rounded-full bg-brand/70"
                      style={{ width: `${Math.max(4, (item.count / data.reportCount) * 160)}px` }} />
                <span className="font-mono text-[11px] text-fg-subtle">{item.count}</span>
              </li>
            ))}
          </ul>
        </DashboardCard>

        <DashboardCard title="Review queue" subtitle="Nothing reaches workers until it is published"
                       icon={Flag} iconColor="#d97706">
          <ul className="space-y-1.5">
            {Object.entries(data.hotspotsByStatus).map(([status, count]) => (
              <li key={status} className="flex items-center justify-between gap-2">
                <StatusPill status={status} />
                <span className="font-mono text-[12px] text-fg">{count}</span>
              </li>
            ))}
            {Object.keys(data.hotspotsByStatus).length === 0 && (
              <li className="text-xs text-fg-muted">No candidate hotspots yet.</li>
            )}
          </ul>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" icon={MapPin} onClick={() => navigate('admin-map')}>Safety Map</Button>
            <Button size="sm" variant="ghost" icon={Flag} onClick={() => navigate('admin-hotspots')}>Hotspots</Button>
            <Button size="sm" variant="ghost" icon={FileText} onClick={() => navigate('admin-reports')}>Reports</Button>
            <Button size="sm" variant="ghost" icon={Bell} onClick={() => navigate('admin-announcements')}>Announcements</Button>
          </div>
        </DashboardCard>
      </div>

      <DashboardCard title="Safety Assistant"
                     subtitle="Answers drawn from this project's records"
                     icon={ClipboardList} iconColor="#0891b2">
        <div className="h-[420px]">
          <SafetyChat role="admin" onOpenRoute={() => navigate('admin-worker-routes')} />
        </div>
      </DashboardCard>

      <p className="text-[11px] leading-relaxed text-fg-subtle">{data.disclaimer}</p>
    </div>
  );
}

// --- reports --------------------------------------------------------------------------------

export function AdminReportsPage() {
  const { api } = useSettings();
  const [rows, setRows] = useState<AdminReportRow[]>([]);
  const [detail, setDetail] = useState<AdminReportDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows((await api.adminReports()).reports);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load reports.');
    }
  }, [api]);
  useEffect(() => { void load(); }, [load]);

  const open = async (id: number) => {
    try {
      setDetail(await api.adminReportDetail(id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load report details.');
    }
  };

  return (
    <div className="space-y-4">
      <DashboardCard title="Safety Reports" subtitle="Live feed from workers in the field"
                     icon={FileText} iconColor="#2563eb"
                     actions={<Button size="sm" variant="ghost" icon={RefreshCw} onClick={() => void load()}>Refresh</Button>}>
        {error && <p className="mb-2 text-xs text-risk-high">{error}</p>}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-black/[0.06] text-fg-subtle">
                <th className="pb-2 font-medium">ID</th>
                <th className="pb-2 font-medium">Worker</th>
                <th className="pb-2 font-medium">Summary</th>
                <th className="pb-2 font-medium">Risk</th>
                <th className="pb-2 font-medium">Location</th>
                <th className="pb-2 font-medium">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.04]">
              {rows.map((row) => (
                <tr key={row.id} className="cursor-pointer hover:bg-black/[0.02]"
                    onClick={() => void open(row.id)}>
                  <td className="py-2 font-mono text-fg-subtle">SR-{row.id}</td>
                  <td className="py-2 text-fg">
                    <span className="font-medium">{row.workerName ?? 'Staff'}</span>
                    {row.employeeId && <span className="ml-1 font-mono text-[10px] text-fg-subtle">({row.employeeId})</span>}
                  </td>
                  <td className="py-2 text-fg truncate max-w-xs">{row.reportText}</td>
                  <td className="py-2">
                    {row.riskLevel && <RiskBadge level={toDisplayRisk(row.riskLevel)} size="sm" />}
                  </td>
                  <td className="py-2 text-fg-muted">{row.locationText ?? '—'}</td>
                  <td className="py-2 font-mono text-[10px] text-fg-subtle">
                    {row.createdAt ? row.createdAt.slice(0, 16).replace('T', ' ') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DashboardCard>

      {detail && <ReportDetailCard detail={detail} onRefresh={() => void open(detail.report.id)} />}
    </div>
  );
}

function ReportDetailCard({ detail, onRefresh }: { detail: AdminReportDetail; onRefresh: () => void }) {
  const { api } = useSettings();
  const { evidence, report, analysis, pattern, geographicRelationship, recommendations, incidentHistory, explanation } = detail;
  const photoSrc = evidence.photoUrl ? api.absoluteUrl(evidence.photoUrl) : null;

  const riskFactors = Array.isArray(analysis?.riskFactors)
    ? (analysis.riskFactors as string[])
    : Array.isArray(analysis?.hazards)
    ? (analysis.hazards as string[])
    : Array.isArray(report?.riskFactors)
    ? (report.riskFactors as string[])
    : [];

  const recList: string[] = [];
  if (recommendations) {
    if (Array.isArray(recommendations)) {
      recList.push(...recommendations.map(String));
    } else if (typeof recommendations === 'object') {
      Object.entries(recommendations).forEach(([k, v]) => {
        if (v) recList.push(`${k.replace(/_/g, ' ')}: ${String(v)}`);
      });
    }
  }

  return (
    <DashboardCard
      title={`Report SR-${report.id}`}
      subtitle={`Worker: ${String(report.workerName || report.employeeId || 'Worker')} (${String(report.employeeId || 'EMP')})`}
      icon={FileText}
      iconColor="#7c3aed"
      actions={
        report.riskLevel
          ? <RiskBadge level={toDisplayRisk(report.riskLevel)} suffix="RISK" size="md" />
          : undefined
      }
    >
      <div className="space-y-4">
        {/* 1. Incident: ID, Worker ID, text */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1 flex items-center gap-1.5 font-semibold text-fg">
            <FileText className="size-3" /> 1. Incident Details
          </p>
          <div className="flex flex-wrap items-center gap-2 mb-1.5 text-xs text-fg-subtle">
            <span className="font-mono font-medium text-fg">Report ID: SR-{report.id}</span>
            <span>·</span>
            <span>Worker: <span className="font-medium text-fg">{String(report.workerName || 'Staff')}</span></span>
            <span>·</span>
            <span className="font-mono text-fg-muted">Employee ID: {String(report.employeeId || '—')}</span>
            {report.createdAt && (
              <>
                <span>·</span>
                <span>{String(report.createdAt).slice(0, 16).replace('T', ' ')}</span>
              </>
            )}
          </div>
          <p className="text-[13px] leading-relaxed text-fg">{report.reportText}</p>
          {detail.domain.matchedText && (
            <p className="mt-1.5 text-[11px] text-fg-subtle">
              Category: <span className="text-fg-muted">{detail.domain.label}</span> (matched “{detail.domain.matchedText}”)
            </p>
          )}
        </div>

        {/* 2. Extracted Risk Factors */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1.5 font-semibold text-fg">2. Extracted Risk Factors</p>
          {riskFactors.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {riskFactors.map((rf, i) => (
                <Chip key={i}>{rf}</Chip>
              ))}
            </div>
          ) : (
            <p className="text-xs text-fg-muted">No explicit risk factors tagged.</p>
          )}
        </div>

        {/* 3. Risk Classification */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1.5 font-semibold text-fg">3. Risk Classification</p>
          <div className="flex items-center gap-2 mb-1.5">
            {report.riskLevel && (
              <RiskBadge level={toDisplayRisk(report.riskLevel)} suffix="RISK" size="sm" />
            )}
            <span className="text-xs font-medium text-fg">
              {String(analysis?.riskLevel || report.riskLevel || 'UNSPECIFIED')}
            </span>
          </div>
          <p className="text-xs leading-relaxed text-fg-muted">
            {String(analysis?.reasoning || analysis?.severityExplanation || analysis?.explanation || 'Evaluated based on reported hazards, operational proximity, and severity thresholds.')}
          </p>
        </div>

        {/* 4. Evidence: Photo & Confirmed GPS Provenance */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1.5 flex items-center gap-1.5 font-semibold text-fg">
            <ImageIcon className="size-3" /> 4. Evidence & Location Provenance
          </p>
          {photoSrc ? (
            <div className="mb-2.5">
              <img
                src={photoSrc}
                alt={`Evidence photo for report ${report.id}`}
                className="max-h-60 w-full rounded-lg object-contain bg-black/[0.04]"
              />
            </div>
          ) : (
            <p className="text-xs text-fg-muted mb-2">No photo was attached to this report.</p>
          )}
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
            {evidence.photoSource && (
              <>
                <dt className="text-fg-subtle">Photo source</dt>
                <dd className="text-fg">{evidence.photoSource === 'live_camera' ? 'Live camera' : 'Upload'}</dd>
              </>
            )}
            {evidence.photoCapturedAt && (
              <>
                <dt className="text-fg-subtle">Photo captured</dt>
                <dd className="text-fg">{evidence.photoCapturedAt.slice(0, 16).replace('T', ' ')}</dd>
              </>
            )}
            <dt className="text-fg-subtle">Location source</dt>
            <dd className="text-fg font-medium">{evidence.locationSource ?? 'unknown'}</dd>
            {evidence.latitude != null && (
              <>
                <dt className="text-fg-subtle">Confirmed GPS</dt>
                <dd className="font-mono text-fg">{evidence.latitude.toFixed(5)}, {evidence.longitude?.toFixed(5)}</dd>
              </>
            )}
            {evidence.gpsAccuracy != null && (
              <>
                <dt className="text-fg-subtle">GPS accuracy</dt>
                <dd className="text-fg">±{Math.round(evidence.gpsAccuracy)} m</dd>
              </>
            )}
          </dl>
          <p className="mt-1.5 text-[10.5px] text-fg-subtle">{evidence.geotagNote}</p>
        </div>

        {/* 5. Pattern Status (with Precursor Logic) */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1.5 font-semibold text-fg">5. Pattern Status</p>
          {pattern ? (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-brand/10 border border-brand/25 px-2.5 py-0.5 text-[10.5px] font-semibold text-brand">
                  Level {pattern.level}: {pattern.status.replace(/_/g, ' ')}
                </span>
              </div>
              <p className="text-xs text-fg-muted">{pattern.summary}</p>
              {(pattern.isPrecursor || pattern.precursorNote) && (
                <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/[0.08] p-2.5">
                  <p className="text-xs font-semibold text-amber-700 flex items-center gap-1.5">
                    <AlertTriangle className="size-3.5 text-amber-600" /> Possible Incident Precursor
                  </p>
                  <p className="mt-0.5 text-[11.5px] leading-relaxed text-fg-muted">
                    {pattern.precursorNote || 'Repeated near-miss reports may indicate an emerging safety precursor in this area.'}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-fg-muted">Level 1: Single incident. No recurring pattern detected in this area.</p>
          )}
        </div>

        {/* 6. Geographic Relationship */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1.5 flex items-center gap-1.5 font-semibold text-fg">
            <MapPin className="size-3" /> 6. Geographic Relationship (Within 1 km)
          </p>
          {geographicRelationship && geographicRelationship.length > 0 ? (
            <ul className="space-y-1.5">
              {geographicRelationship.map((rel) => (
                <li key={rel.reportId} className="rounded-lg border border-black/[0.06] bg-white p-2 text-xs">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono font-medium text-fg">SR-{rel.reportId}</span>
                    <span className="font-mono text-[10.5px] text-fg-subtle">
                      {rel.distanceMeters != null ? `${rel.distanceMeters} m away` : 'Co-located'}
                    </span>
                  </div>
                  {rel.location && <p className="text-[11.5px] text-fg-muted">{rel.location}</p>}
                  {rel.hazards.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {rel.hazards.map((h) => <Chip key={h}>{h}</Chip>)}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-fg-muted">No other reports located within 1 km of this incident.</p>
          )}
        </div>

        {/* 7. Historical Incidents */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1.5 font-semibold text-fg">7. Historical Incidents</p>
          <IncidentHistoryPanel history={incidentHistory} />
        </div>

        {/* 8. Recommendations */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1.5 font-semibold text-fg">8. Recommended Actions</p>
          {recList.length > 0 ? (
            <ul className="space-y-1">
              {recList.map((rec, idx) => (
                <li key={idx} className="flex items-start gap-1.5 text-xs text-fg-muted">
                  <span className="text-brand font-bold">•</span>
                  <span>{rec}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-fg-muted">No immediate automated actions prescribed. Follow standard operating safety procedures.</p>
          )}
        </div>

        {/* 9. Explainable AI Assessment Statement */}
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <p className="eyebrow mb-1.5 font-semibold text-fg">9. Explainable AI Assessment</p>
          <ExplanationPanel explanation={explanation} />
        </div>

        {/* Action Tracker */}
        <ActionTracker reportId={report.id} actions={detail.adminActions} onRecorded={onRefresh} />
      </div>
    </DashboardCard>
  );
}

// --- hotspots (review queue) --------------------------------------------------------------------

const REVIEW_ACTIONS = [
  { id: 'acknowledge', label: 'Acknowledge' },
  { id: 'investigate', label: 'Investigate' },
  { id: 'resolve', label: 'Resolve' },
  { id: 'dismiss', label: 'Dismiss' },
];

export function AdminHotspotsPage() {
  const { api } = useSettings();
  const [rows, setRows] = useState<SafetyHotspot[]>([]);
  const [detail, setDetail] = useState<HotspotDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows((await api.adminHotspots()).hotspots);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load hotspots.');
    }
  }, [api]);
  useEffect(() => { void load(); }, [load]);

  const open = useCallback(async (id: number) => {
    try {
      setDetail(await api.adminHotspotDetail(id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load the hotspot.');
    }
  }, [api]);

  const act = async (action: string) => {
    if (!detail) return;
    setBusy(true);
    try {
      await api.adminHotspotAction(detail.hotspot.id, action);
      await open(detail.hotspot.id);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Could not ${action}.`);
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!detail) return;
    setBusy(true);
    try {
      const hotspot = detail.hotspot;
      await api.adminPublishAnnouncement({
        title: `Safety Alert — ${hotspot.locations[0] ?? hotspot.primaryHazard ?? 'Flagged location'}`,
        message: `${hotspot.primaryHazard ?? 'A hazard'} has been reported in this area. ` +
                 'Please avoid the marked area until the safety team completes inspection.',
        severity: hotspot.riskLevel, hotspotId: hotspot.id,
        latitude: hotspot.latitude, longitude: hotspot.longitude,
        locationText: hotspot.locations[0] ?? null,
      });
      await open(hotspot.id);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not publish.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.3fr)]">
      <DashboardCard title="Candidate hotspots" subtitle={`${rows.length} on record`}
                     icon={Flag} iconColor="#dc2626">
        {error && <p className="mb-2 text-xs text-risk-high">{error}</p>}
        {rows.length === 0 && <p className="text-xs text-fg-muted">No candidate hotspots yet.</p>}
        <ul className="max-h-[70vh] space-y-1.5 overflow-y-auto pr-1">
          {rows.map((row) => (
            <li key={row.id}>
              <button type="button" onClick={() => void open(row.id)}
                      className="w-full rounded-lg border border-black/[0.06] bg-black/[0.02] px-2.5 py-2 text-left transition hover:border-brand/30">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[12.5px] font-semibold text-fg">{row.primaryHazard}</span>
                  <StatusPill status={row.status} />
                </div>
                <p className="mt-0.5 text-[11.5px] text-fg-muted">
                  {row.reportCount} related reports within {row.radiusMeters} m
                </p>
                <DataModeBadge tone={row.isAiDetected ? 'live' : 'historical'}
                               label={row.isAiDetected ? 'AI detected' : 'Admin flagged'} size="sm" />
              </button>
            </li>
          ))}
        </ul>
      </DashboardCard>

      {detail && (
        <DashboardCard
          title={detail.hotspot.isAiDetected ? 'AI-Detected Candidate Hotspot' : 'Admin-Flagged Location'}
          subtitle={detail.hotspot.explanation ?? ''}
          icon={detail.hotspot.isAiDetected ? ShieldAlert : Flag}
          iconColor={detail.hotspot.isAiDetected ? '#dc2626' : '#d97706'}
          actions={<StatusPill status={detail.hotspot.status} />}
        >
          <div className="flex items-center gap-2">
            <RiskBadge level={toDisplayRisk(detail.hotspot.riskLevel)} suffix="RISK" size="md" />
            <span className="text-[13px] text-fg">{detail.hotspot.primaryHazard}</span>
          </div>
          <p className="mt-1 text-xs text-fg-muted">
            {detail.hotspot.reportCount} related reports within {detail.hotspot.radiusMeters} m
            {detail.hotspot.locations.length > 0 && ` · ${detail.hotspot.locations.join(', ')}`}
          </p>
          <p className="mt-0.5 font-mono text-[10.5px] text-fg-subtle">
            Supporting: {detail.hotspot.reportIds.map((id) => `SR-${id}`).join(', ')}
          </p>
          <p className="mt-0.5 font-mono text-[10.5px] text-fg-subtle">
            First {detail.hotspot.firstReportAt?.slice(0, 10)} · Latest {detail.hotspot.latestReportAt?.slice(0, 10)}
          </p>

          <div className="mt-3 space-y-2.5">
            {detail.supportingReports.length > 0 && (
              <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
                <p className="eyebrow mb-1.5">Supporting reports</p>
                <ul className="max-h-40 space-y-1.5 overflow-y-auto pr-1">
                  {detail.supportingReports.map((report) => (
                    <li key={report.id} className="rounded-lg border border-black/[0.06] bg-white/60 px-2.5 py-1.5">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-mono text-[10px] text-fg-subtle">SR-{report.id}</span>
                        {report.riskLevel && <RiskBadge level={toDisplayRisk(report.riskLevel)} size="sm" />}
                      </div>
                      <p className="mt-0.5 text-[11.5px] leading-relaxed text-fg-muted">{report.reportText}</p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <IncidentHistoryPanel history={detail.incidentHistory} />
            <ExplanationPanel explanation={detail.explanation} />
            <SpecializedResponsePanel response={detail.specializedResponse} authority={detail.authority} />
            <ActionTracker hotspotId={detail.hotspot.id} actions={detail.adminActions}
                           onRecorded={() => void open(detail.hotspot.id)} />
            <FeedbackControl hotspotId={detail.hotspot.id} />
          </div>

          <div className="mt-4 flex flex-wrap gap-2 border-t border-black/[0.06] pt-3">
            {REVIEW_ACTIONS.map((action) => (
              <Button key={action.id} size="sm" variant="ghost" disabled={busy}
                      onClick={() => void act(action.id)}>{action.label}</Button>
            ))}
            <Button size="sm" variant="primary" disabled={busy || detail.hotspot.status === 'PUBLISHED'}
                    onClick={() => void publish()}>
              {detail.hotspot.status === 'PUBLISHED' ? 'Alert published ✓' : 'Publish Alert'}
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

// --- announcements ----------------------------------------------------------------------------

export function AdminAnnouncementsPage() {
  const { api } = useSettings();
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setRows((await api.adminAnnouncements()).announcements);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Could not load announcements.');
      }
    })();
  }, [api]);

  return (
    <DashboardCard title="Published alerts" subtitle="What workers can currently see"
                   icon={Bell} iconColor="#dc2626">
      {error && <p className="mb-2 text-xs text-risk-high">{error}</p>}
      {rows.length === 0 && <p className="text-xs text-fg-muted">Nothing has been published yet.</p>}
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={String(row.id)} className="rounded-lg border border-risk-high/20 bg-risk-high/[0.05] px-3 py-2.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[13px] font-semibold text-fg">⚠️ {String(row.title)}</span>
              <StatusPill status={String(row.status)} />
            </div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-fg-muted">{String(row.message)}</p>
            <p className="mt-1 font-mono text-[10px] text-fg-subtle">
              {String(row.locationText ?? 'Location on map')} · {String(row.createdAt).slice(0, 16).replace('T', ' ')}
            </p>
          </li>
        ))}
      </ul>
    </DashboardCard>
  );
}
