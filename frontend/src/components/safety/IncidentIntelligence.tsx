/**
 * The evidence an admin needs before deciding anything: what has happened here before, what the
 * system concluded from that, and who is relevant to call.
 *
 * Every number on this panel is a count of stored reports, and every authority is an
 * OpenStreetMap object. Nothing is generated prose. That is why report ids are printed beside
 * each claim — the admin can open the reports and check the assertion rather than trust it.
 *
 * The recommendation is always phrased as something a human should consider doing. The system
 * contacts nobody, and the panel says so where the buttons are, not in a footnote.
 */
import { CheckCircle2, History, Phone, ShieldAlert, ThumbsDown, ThumbsUp } from 'lucide-react';
import { useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import type {
  AdminActionRow, AuthorityLookup, ExplainableAssessment, IncidentHistory, SpecializedResponse,
} from '../../types/safety';
import { Button } from '../ui/Button';
import { Chip } from '../ui/primitives';

const ACTIONS = [
  { id: 'contacted_police', label: 'Contacted Police' },
  { id: 'contacted_fire_service', label: 'Contacted Fire Service' },
  { id: 'contacted_wildlife_authority', label: 'Contacted Wildlife Authority' },
  { id: 'contacted_electrical_service', label: 'Contacted Electrical Service' },
  { id: 'contacted_emergency_medical', label: 'Contacted Emergency Medical' },
  { id: 'internal_team_notified', label: 'Internal Team Notified' },
  { id: 'no_action_required', label: 'No Action Required' },
];

const FEEDBACK_REASONS = [
  { id: 'wrong_authority', label: 'Wrong authority' },
  { id: 'incorrect_location', label: 'Incorrect location' },
  { id: 'incorrect_classification', label: 'Incorrect classification' },
  { id: 'contact_unavailable', label: 'Contact unavailable' },
  { id: 'not_applicable', label: 'Not applicable' },
  { id: 'authority_did_not_respond', label: 'Authority did not respond' },
  { id: 'other', label: 'Other' },
];

// --- incident history ---------------------------------------------------------------------------

export function IncidentHistoryPanel({ history }: { history: IncidentHistory | null }) {
  if (!history) return null;
  const km = (history.radiusMeters / 1000).toFixed(0);

  if (history.reportCount === 0) {
    return (
      <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
        <p className="eyebrow mb-1 flex items-center gap-1.5"><History className="size-3" /> Incident history</p>
        <p className="text-xs text-fg-muted">
          {history.unavailableReason ?? `No previous reports on record within ${km} km.`}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
      <p className="eyebrow mb-1.5 flex items-center gap-1.5"><History className="size-3" /> Previous incidents in this area</p>
      <p className="text-[13px] text-fg">
        {history.reportCount} previous report{history.reportCount === 1 ? '' : 's'} within {km} km
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <Chip>{history.riskBreakdown.HIGH} HIGH</Chip>
        <Chip>{history.riskBreakdown.MEDIUM} MEDIUM</Chip>
        <Chip>{history.riskBreakdown.LOW} LOW</Chip>
      </div>

      {history.recurringHazards.length > 0 && (
        <div className="mt-2">
          <p className="text-[11px] text-fg-subtle">Recurring</p>
          <ul className="mt-0.5 space-y-0.5">
            {history.recurringHazards.slice(0, 5).map((item) => (
              <li key={item.hazard} className="text-[12px] text-fg-muted">
                · {item.hazard} <span className="text-fg-subtle">×{item.count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {history.incidentTypes.length > 0 && (
        <p className="mt-2 text-[11.5px] text-fg-muted">
          Types: {history.incidentTypes.map((t) => `${t.type} (${t.count})`).join(', ')}
        </p>
      )}

      {history.seriousIncidentCount > 0 && (
        <div className="mt-2 rounded-lg border border-risk-high/25 bg-risk-high/[0.06] px-2.5 py-2">
          <p className="text-[11.5px] font-semibold text-risk-high">
            {history.seriousIncidentCount} serious incident
            {history.seriousIncidentCount === 1 ? '' : 's'} on record
          </p>
          <ul className="mt-1 space-y-1">
            {history.seriousIncidents.slice(0, 4).map((item) => (
              <li key={item.reportId} className="text-[11.5px] leading-relaxed text-fg-muted">
                <span className="font-mono text-[10px] text-fg-subtle">SR-{item.reportId}</span>{' '}
                {item.markers.join(', ')} — <span className="italic">{item.evidence}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {history.previousRecommendations.length > 0 && (
        <div className="mt-2">
          <p className="text-[11px] text-fg-subtle">Previously recommended here</p>
          <ul className="mt-0.5 space-y-0.5">
            {history.previousRecommendations.slice(0, 3).map((item) => (
              <li key={item.reportId} className="text-[11.5px] text-fg-muted">
                <span className="font-mono text-[10px] text-fg-subtle">SR-{item.reportId}</span>{' '}
                {item.actions[0]}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-2 font-mono text-[10px] text-fg-subtle">
        {history.firstReportAt && `First ${history.firstReportAt.slice(0, 10)}`}
        {history.latestReportAt && ` · Latest ${history.latestReportAt.slice(0, 10)}`}
      </p>
    </div>
  );
}

// --- explainable assessment ---------------------------------------------------------------------

export function ExplanationPanel({ explanation }: { explanation: ExplainableAssessment | null }) {
  if (!explanation) return null;
  return (
    <div className="rounded-lg border border-info/20 bg-info/[0.05] px-3 py-2.5">
      <p className="eyebrow mb-1">Explainable AI assessment</p>
      <p className="text-[12.5px] leading-relaxed text-fg">{explanation.statement}</p>
      {explanation.evidenceReportIds.length > 0 && (
        <p className="mt-1.5 font-mono text-[10px] text-fg-subtle">
          Evidence: {explanation.evidenceReportIds.slice(0, 12).map((id) => `SR-${id}`).join(', ')}
          {explanation.evidenceReportIds.length > 12 && ` +${explanation.evidenceReportIds.length - 12} more`}
        </p>
      )}
      {/* Says what the assessment is made of, so it is not mistaken for a measurement. */}
      <p className="mt-1 text-[10.5px] text-fg-subtle">
        Derived from {explanation.basis}. A pattern in reports is evidence about reporting, not a
        measurement of current conditions.
      </p>
    </div>
  );
}

// --- specialised emergency response ---------------------------------------------------------------

export function SpecializedResponsePanel({
  response, authority,
}: { response: SpecializedResponse | null; authority?: AuthorityLookup | null }) {
  const lookup = response?.authority ?? authority;
  if (!response && !lookup?.available) return null;

  return (
    <div className="rounded-lg border border-risk-high/25 bg-risk-high/[0.05] px-3 py-2.5">
      <p className="eyebrow mb-1 flex items-center gap-1.5">
        <ShieldAlert className="size-3" /> {response ? `${response.label} response` : 'Nearby authority'}
      </p>

      {lookup && !lookup.available && (
        // The failure is printed, not swallowed: an admin who sees nothing cannot tell whether
        // there is no station nearby or the lookup never ran.
        <p className="text-[12px] text-fg-muted">{lookup.reason ?? 'Authority lookup unavailable.'}</p>
      )}

      {lookup?.available && lookup.results.length === 0 && (
        <p className="text-[12px] text-fg-muted">{lookup.reason}</p>
      )}

      {lookup?.available && lookup.results.length > 0 && (
        <ul className="space-y-1.5">
          {lookup.results.map((item) => (
            <li key={item.osmId} className="rounded-lg border border-black/[0.06] bg-white/60 px-2.5 py-2">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12.5px] font-semibold text-fg">{item.name}</span>
                <span className="shrink-0 font-mono text-[10px] text-fg-subtle">
                  {(item.distanceMeters / 1000).toFixed(1)} km
                </span>
              </div>
              {item.address && <p className="text-[11px] text-fg-muted">{item.address}</p>}
              <p className="mt-0.5 flex items-center gap-1.5 text-[11.5px]">
                <Phone className="size-3 text-fg-subtle" />
                {item.phone
                  ? <span className="text-fg">{item.phone}</span>
                  /* No number in OSM means no number shown. Never a plausible substitute. */
                  : <span className="text-fg-subtle">Not listed in OpenStreetMap</span>}
                {item.verified && <span className="text-[10px] text-risk-low">· from OSM data</span>}
              </p>
            </li>
          ))}
        </ul>
      )}

      {response && (
        <>
          <p className="mt-2 text-[12px] leading-relaxed text-fg">{response.recommendation}</p>
          {response.evidenceReportIds && response.evidenceReportIds.length > 0 && (
            <p className="mt-1 font-mono text-[10px] text-fg-subtle">
              Evidence: {response.evidenceReportIds.map((id) => `SR-${id}`).join(', ')}
            </p>
          )}
          <p className="mt-1 text-[10.5px] leading-relaxed text-fg-subtle">{response.disclaimer}</p>
        </>
      )}

      {lookup?.source && (
        <p className="mt-1 font-mono text-[10px] text-fg-subtle">Source: {lookup.source}</p>
      )}
    </div>
  );
}

// --- action tracking and feedback -----------------------------------------------------------------

export function ActionTracker({
  hotspotId, reportId, actions, onRecorded,
}: {
  hotspotId?: number | null;
  reportId?: number | null;
  actions: AdminActionRow[];
  onRecorded: () => void;
}) {
  const { api } = useSettings();
  const [busy, setBusy] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);

  const record = async (actionTaken: string) => {
    setBusy(actionTaken);
    setError(null);
    try {
      await api.adminRecordAction({ actionTaken, hotspotId, reportId, adminNotes: notes || null });
      setNotes('');
      onRecorded();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record the action.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
      <p className="eyebrow mb-1.5">Record what you did</p>
      <input
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
        placeholder="Optional note — who you spoke to, what was agreed…"
        className="mb-2 w-full rounded-lg border border-black/[0.08] bg-white/60 px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand/40"
      />
      <div className="flex flex-wrap gap-1.5">
        {ACTIONS.map((action) => (
          <Button key={action.id} size="sm" variant="ghost" disabled={busy !== null}
                  loading={busy === action.id} onClick={() => void record(action.id)}>
            {action.label}
          </Button>
        ))}
      </div>
      {/* The buttons say "Contacted X" — this line makes sure that reads as a log entry. */}
      <p className="mt-1.5 text-[10.5px] text-fg-subtle">
        These record an action you took. EcoSentinel does not contact any authority.
      </p>
      {error && <p className="mt-1.5 text-[11px] text-risk-high">{error}</p>}

      {actions.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-black/[0.06] pt-2">
          {actions.map((action) => (
            <li key={action.id} className="flex items-baseline gap-2 text-[11.5px] text-fg-muted">
              <CheckCircle2 className="size-3 shrink-0 text-risk-low" />
              <span className="text-fg">{action.label}</span>
              {action.authorityContacted && <span>· {action.authorityContacted}</span>}
              {action.adminNotes && <span className="italic">· {action.adminNotes}</span>}
              <span className="ml-auto shrink-0 font-mono text-[10px] text-fg-subtle">
                {action.actionTimestamp.slice(0, 16).replace('T', ' ')}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FeedbackControl({
  hotspotId, reportId, onRecorded,
}: { hotspotId?: number | null; reportId?: number | null; onRecorded?: () => void }) {
  const { api } = useSettings();
  const [given, setGiven] = useState<boolean | null>(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (useful: boolean, reason?: string) => {
    setError(null);
    try {
      await api.adminRecordFeedback({ useful, hotspotId, reportId, reason: reason ?? null });
      setDone(true);
      onRecorded?.();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not record the feedback.');
    }
  };

  if (done) {
    return <p className="text-[11.5px] text-fg-muted">Thanks — feedback recorded.</p>;
  }

  return (
    <div>
      <p className="eyebrow mb-1.5">Was this recommendation useful?</p>
      {given === null && (
        <div className="flex gap-1.5">
          <Button size="sm" variant="ghost" icon={ThumbsUp} onClick={() => void send(true)}>Yes</Button>
          <Button size="sm" variant="ghost" icon={ThumbsDown} onClick={() => setGiven(false)}>No</Button>
        </div>
      )}
      {given === false && (
        <div className="flex flex-wrap gap-1.5">
          {FEEDBACK_REASONS.map((reason) => (
            <Button key={reason.id} size="sm" variant="ghost" onClick={() => void send(false, reason.id)}>
              {reason.label}
            </Button>
          ))}
        </div>
      )}
      {/* Prevents the expectation that a thumbs-down changes the next classification. */}
      <p className="mt-1.5 text-[10.5px] text-fg-subtle">
        Stored for later analysis. A single feedback event never retrains the model.
      </p>
      {error && <p className="mt-1 text-[11px] text-risk-high">{error}</p>}
    </div>
  );
}
