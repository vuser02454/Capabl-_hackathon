/**
 * Contamination flag, live location, and the prompt to report it.
 *
 * Fires when a photo or a live camera frame resembles reference frames labelled as contaminated.
 * The wording is deliberate: "looks like" and "resembles", never "is contaminated". The matcher
 * recognises visibly dirty water well but misreads clean water often (see the caveat it carries),
 * so this is a prompt to look — the user decides whether it is worth reporting.
 *
 * Location is requested only after a flag, and only when the user presses the button: nothing is
 * tracked in the background, and the fix leaves the device only when a report is confirmed.
 */
import { Droplets, LoaderCircle, MapPin, Megaphone, ShieldAlert, TriangleAlert } from 'lucide-react';
import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { useLiveLocation } from '../../hooks/useLiveLocation';
import { cn, pct } from '../../lib/format';
import type { RiskLevel, WaterDatasetMatch } from '../../types/agents';
import { Button } from '../ui/Button';
import { ContaminationReportDialog } from './ContaminationReportDialog';

interface ContaminationAlertProps {
  match: WaterDatasetMatch;
  /** Evidence frame as a data URI, attached to the report when present. */
  photo: string | null;
  source: 'upload' | 'camera';
  waterRiskLevel?: RiskLevel | null;
  waterRiskScore?: number | null;
}

export function ContaminationAlert({ match, photo, source, waterRiskLevel, waterRiskScore }: ContaminationAlertProps) {
  const { location, waterBody, identifyingWater, tracking, locating, error, resolvingPlace, start, stop } =
    useLiveLocation();
  const [dialogOpen, setDialogOpen] = useState(false);

  // Stop tracking as soon as the flag clears, so location never outlives the reason for it.
  useEffect(() => {
    if (!match.contaminated && tracking) stop();
  }, [match.contaminated, tracking, stop]);

  if (!match.contaminated) return null;

  const place =
    location?.displayName ??
    [location?.neighbourhood, location?.city, location?.state].filter(Boolean).join(', ');

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-2xl border border-risk-high/30 bg-risk-high/[0.07] p-4"
      role="alert"
    >
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl border border-risk-high/30 bg-risk-high/10">
          <ShieldAlert className="size-[18px] text-risk-high" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold tracking-tight text-fg">
            This looks like contaminated water
          </h3>
          <p className="mt-1 text-[12.5px] leading-relaxed text-fg-muted">
            The {source === 'camera' ? 'camera frame' : 'photo'} resembles reference frames labelled{' '}
            <span className="font-medium text-fg">{match.matchedLabel ?? match.matchedClass}</span>
            {match.similarity != null && <> at {pct(match.similarity)}% similarity</>}
            {match.voteShare != null && <>, with {pct(match.voteShare)}% of the nearest frames agreeing</>}.
          </p>
          {match.caveat && (
            <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-fg-subtle">
              <TriangleAlert className="mt-px size-3.5 shrink-0 text-risk-moderate" />
              <span>{match.caveat}</span>
            </p>
          )}
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-black/[0.07] bg-ink-950/30 px-3 py-2.5">
        <p className="flex items-center gap-1.5 text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">
          <MapPin className="size-3" /> Your location
        </p>
        {location ? (
          <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <p className="tabular text-[13px] font-semibold text-fg">
              {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)}
            </p>
            <p className="text-[11px] text-fg-subtle">
              {location.accuracyM != null && <>±{Math.round(location.accuracyM)} m</>}
              {tracking && <> · updating live</>}
            </p>
            <p className="w-full truncate text-[11px] text-fg-muted">
              {place || (resolvingPlace ? 'Naming this place…' : 'Place name unavailable — coordinates are enough')}
            </p>
            {/* Which water body this is, from OpenStreetMap. A report naming "Bellandur Lake" is
                actionable in a way that bare coordinates are not. */}
            <p className="flex w-full items-center gap-1.5 text-[11px] text-fg-muted">
              <Droplets className="size-3 shrink-0 text-agent-water" />
              {waterBody ? (
                <span className="truncate">
                  <span className="font-medium text-fg">{waterBody.name}</span>
                  <span className="text-fg-subtle">
                    {' '}
                    · {waterBody.label} · {Math.round(waterBody.distanceKm * 1000)} m away
                  </span>
                </span>
              ) : (
                <span className="text-fg-subtle">
                  {identifyingWater ? 'Identifying the water body…' : 'No mapped water body identified nearby'}
                </span>
              )}
            </p>
          </div>
        ) : error ? (
          <p className="mt-1 text-[11.5px] text-risk-moderate">{error}</p>
        ) : (
          <p className="mt-1 text-[11.5px] text-fg-muted">
            {locating
              ? 'Getting a GPS fix…'
              : 'A report needs coordinates. Your location is only read after you press the button below, and only leaves this device if you confirm a report.'}
          </p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {!location && (
          <Button
            size="sm"
            icon={locating ? undefined : MapPin}
            loading={locating}
            onClick={start}
            disabled={tracking && locating}
          >
            {locating ? 'Locating…' : 'Use my location'}
          </Button>
        )}
        <Button
          size="sm"
          variant="primary"
          icon={Megaphone}
          disabled={!location}
          onClick={() => setDialogOpen(true)}
        >
          Report to authorities
        </Button>
      </div>

      <ContaminationReportDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        location={location}
        match={match}
        photo={photo}
        source={source}
        waterRiskLevel={waterRiskLevel}
        waterRiskScore={waterRiskScore}
      />
    </motion.section>
  );
}

/** Compact live verdict drawn over the camera preview while it scans. */
export function LiveScanBadge({
  match,
  scanning,
  disabled,
}: {
  match: WaterDatasetMatch | null;
  scanning: boolean;
  disabled?: string;
}) {
  if (disabled) {
    return (
      <p className="rounded-lg bg-ink-950/80 px-2.5 py-1.5 text-center text-[11px] text-fg-subtle backdrop-blur-sm">
        {disabled}
      </p>
    );
  }

  const flagged = match?.contaminated;
  const label = !match
    ? 'Scanning…'
    : match.status === 'ok'
      ? `${flagged ? 'Looks like' : 'Closest match'}: ${match.matchedLabel ?? match.matchedClass}`
      : match.status === 'no_match'
        ? 'No reference match'
        : (match.message ?? 'Scan unavailable');

  return (
    <p
      className={cn(
        'flex items-center justify-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium backdrop-blur-sm',
        flagged ? 'bg-risk-high/85 text-ink-950' : 'bg-ink-950/80 text-fg-muted',
      )}
    >
      {scanning && <LoaderCircle className="size-3 animate-spin" />}
      {flagged && <ShieldAlert className="size-3.5" />}
      <span className="truncate">{label}</span>
      {match?.similarity != null && match.status === 'ok' && <span className="tabular">{pct(match.similarity)}%</span>}
    </p>
  );
}
