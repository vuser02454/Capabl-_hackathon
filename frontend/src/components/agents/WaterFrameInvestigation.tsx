/**
 * Live visual monitoring, then a full investigation of one chosen frame.
 *
 *     LIVE ANALYSIS  →  click a frame  →  EXPLAINABLE AI INVESTIGATION
 *
 * The split is deliberate. While the camera runs, the UI stays a single line of status: no
 * reasons, no recovery plan, no report. Producing a full explanation for every sampled frame
 * would be expensive, would fire a contamination narrative at footage the user was only pointing
 * around the room, and would train people to ignore it. The costly, detailed work happens once,
 * on a frame someone deliberately chose.
 *
 * Geolocation is requested only at that moment, and only as provenance. A denial is not an error
 * here — the visual investigation runs unchanged and the report says the location is unavailable.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { Camera, Crosshair, FileText, Loader2, MapPin, ScanSearch, TriangleAlert } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useSettings } from '../../context/SettingsContext';
import { isAbortError, toAppError } from '../../services/errors';
import { downloadFile } from '../../services/reportExport';
import { buildInvestigationReport, investigationReportFilename } from '../../services/investigationReport';
import type { FrameInvestigation } from '../../types/agents';
import { Button } from '../ui/Button';
import { CameraCapture, cameraSupported } from '../ui/CameraCapture';
import { DashboardCard } from '../ui/DashboardCard';
import { FrameInvestigationPanel } from './FrameInvestigationPanel';

/** The only states the live view is allowed to express. Anything richer belongs post-click. */
type LiveStatus = 'idle' | 'analyzing' | 'clear' | 'potential' | 'insufficient';

const LIVE_COPY: Record<LiveStatus, { text: string; tone: string }> = {
  idle: { text: 'Camera idle', tone: 'text-fg-subtle' },
  analyzing: { text: 'Analyzing…', tone: 'text-fg-muted' },
  clear: { text: 'No visible contamination detected', tone: 'text-risk-low' },
  potential: { text: '⚠ Potential visible pollution detected', tone: 'text-risk-moderate' },
  insufficient: { text: 'Insufficient visual evidence', tone: 'text-fg-subtle' },
};

export function WaterFrameInvestigation() {
  const { api, settings } = useSettings();
  const { state } = useAnalysis();
  const [cameraOpen, setCameraOpen] = useState(false);
  const [live, setLive] = useState<LiveStatus>('idle');
  const [investigating, setInvestigating] = useState(false);
  const [investigation, setInvestigation] = useState<FrameInvestigation | null>(null);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [locationNote, setLocationNote] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const locationName = state.selectedPoint?.displayName ?? state.selectedLocation;
  // Framework 1: an investigation without a location produces a report nobody can act on, so the
  // page establishes one first. A denied browser fix is fine — a typed/selected place works too.
  const hasLocation = Boolean(state.selectedPoint) || Boolean(state.selectedLocation);

  /**
   * One-shot geolocation for this frame. Resolves to null on denial or timeout — never rejects,
   * because a missing location must not stop the visual analysis.
   */
  const captureLocation = useCallback((): Promise<{ latitude: number; longitude: number; accuracy?: number; source: string } | null> => {
    // Prefer a point the user already chose over re-prompting for permission.
    const chosen = state.selectedPoint;
    if (chosen) {
      return Promise.resolve({
        latitude: chosen.latitude,
        longitude: chosen.longitude,
        accuracy: chosen.accuracy ?? undefined,
        source: chosen.source === 'browser' ? 'browser' : 'manual',
      });
    }
    if (typeof navigator === 'undefined' || !navigator.geolocation?.getCurrentPosition) {
      setLocationNote('Location unavailable — investigation can continue without geotagging.');
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) =>
          resolve({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy,
            source: 'browser',
          }),
        () => {
          setLocationNote('Location unavailable — investigation can continue without geotagging.');
          resolve(null);
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
      );
    });
  }, [state.selectedPoint]);

  const investigate = useCallback(
    async (file: File | Blob) => {
      setInvestigating(true);
      setError(null);
      setLocationNote(null);
      setInvestigation(null);
      setFrameUrl((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return URL.createObjectURL(file);
      });

      try {
        const geotag = await captureLocation();
        // The chosen point goes as coordinates; `locationName` is only a fallback label for the
        // preset case. Demo Mode is honoured so a demo run is labelled as demo, not as live.
        const result = await api.investigateFrame(
          file,
          locationName,
          geotag ?? undefined,
          undefined,
          state.selectedPoint,
          settings.demoMode,
        );
        if (result.investigation) setInvestigation(result.investigation);
        else setError('The backend did not return an investigation for this frame.');
      } catch (cause) {
        if (!isAbortError(cause)) {
          // Surface the backend's own message. A generic "check the backend is reachable" hid a
          // perfectly clear 404 INVALID_LOCATION and sent debugging in entirely the wrong
          // direction — the backend was reachable and had said exactly what was wrong.
          setError(toAppError(cause).message);
        }
      } finally {
        setInvestigating(false);
      }
    },
    [api, captureLocation, locationName, state.selectedPoint, settings.demoMode],
  );

  /**
   * Live sampling asks YOLO one question — is there visible contamination — and moves a single
   * status line. Nothing expensive or explanatory runs per frame.
   */
  const onLiveFrame = useCallback(
    async (frame: Blob) => {
      if (settings.demoMode) return;
      setLive('analyzing');
      try {
        const verdict = await api.scanFrame(frame);
        if (verdict.status !== 'ok') setLive('insufficient');
        else setLive(verdict.contaminated ? 'potential' : 'clear');
      } catch {
        setLive('insufficient');
      }
    },
    [api, settings.demoMode],
  );

  return (
    <div className="space-y-4">
      <DashboardCard bodyClassName="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow">Live monitoring</p>
            <p className="mt-0.5 text-sm text-fg">Point the camera at the water, then investigate a frame</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {cameraSupported() && (
              <Button size="sm" icon={Camera} onClick={() => setCameraOpen(true)} disabled={investigating}>
                Open camera
              </Button>
            )}
            <Button
              size="sm"
              variant="secondary"
              icon={ScanSearch}
              loading={investigating}
              onClick={() => fileRef.current?.click()}
            >
              Investigate an image
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void investigate(file);
                event.target.value = '';
              }}
            />
          </div>
        </div>

        {/* Framework 1: where this investigation applies, established before anything is judged. */}
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px]">
          <MapPin className="size-3.5 shrink-0 text-brand" />
          {hasLocation ? (
            <>
              <span className="min-w-0 truncate text-fg">{locationName}</span>
              {state.selectedPoint && (
                <span className="text-fg-subtle tabular">
                  {state.selectedPoint.latitude.toFixed(4)}, {state.selectedPoint.longitude.toFixed(4)}
                  {state.selectedPoint.accuracy != null && ` · ±${Math.round(state.selectedPoint.accuracy)} m`}
                </span>
              )}
              <span className="text-fg-subtle">
                · {state.selectedPoint?.source === 'browser' ? 'browser location' : 'selected location'}
              </span>
            </>
          ) : (
            <span className="text-risk-moderate">
              No location set. Choose one on the Dashboard — a report without a place is hard to act on.
            </span>
          )}
        </div>

        {/* The whole live experience: one line. */}
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
          <span className={cameraOpen ? 'size-2 animate-pulse rounded-full bg-risk-low' : 'size-2 rounded-full bg-white/20'} />
          <span className={`text-xs ${LIVE_COPY[cameraOpen ? live : 'idle'].tone}`}>
            {LIVE_COPY[cameraOpen ? live : 'idle'].text}
          </span>
          {cameraOpen && live === 'potential' && (
            <span className="ml-auto text-[11px] text-fg-subtle">Click the frame to investigate</span>
          )}
        </div>

        {error && (
          <p className="mt-2 flex items-start gap-1.5 text-[11px] text-risk-moderate">
            <TriangleAlert className="mt-px size-3 shrink-0" />
            <span>{error}</span>
          </p>
        )}
        {locationNote && <p className="mt-2 text-[11px] text-fg-subtle">{locationNote}</p>}
      </DashboardCard>

      <CameraCapture
        open={cameraOpen}
        onClose={() => {
          setCameraOpen(false);
          setLive('idle');
        }}
        onCapture={(file) => {
          setCameraOpen(false);
          void investigate(file);
        }}
        title="Investigate frame"
        hint="Capture the frame you want explained"
        fileName="water-frame"
        onFrame={onLiveFrame}
        scanIntervalMs={2500}
        scanOverlay={
          <span className={`text-xs ${LIVE_COPY[live].tone}`}>{LIVE_COPY[live].text}</span>
        }
      />

      <AnimatePresence>
        {investigating && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <DashboardCard bodyClassName="p-5">
              <div className="flex items-center gap-3">
                <Loader2 className="size-4 animate-spin text-brand" />
                <div>
                  <p className="eyebrow !text-brand">✦ Explainable AI investigation</p>
                  <p className="mt-0.5 text-sm text-fg">Analyzing selected frame…</p>
                </div>
              </div>
            </DashboardCard>
          </motion.div>
        )}
      </AnimatePresence>

      {!investigating && investigation && (
        <>
          <FrameInvestigationPanel investigation={investigation} imageUrl={frameUrl} />
          <DashboardCard bodyClassName="p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="eyebrow">Report</p>
                <p className="mt-0.5 text-xs text-fg-muted">
                  Detailed write-up of this investigation, including place, date and time when a
                  location was recorded.
                </p>
              </div>
              <Button
                size="sm"
                icon={FileText}
                onClick={() =>
                  downloadFile(
                    investigationReportFilename(investigation),
                    buildInvestigationReport(investigation),
                    'text/plain',
                  )
                }
              >
                Create report
              </Button>
            </div>
          </DashboardCard>
        </>
      )}

      {!investigating && !investigation && !error && (
        <DashboardCard bodyClassName="p-5">
          <div className="flex items-start gap-2.5 text-xs text-fg-subtle">
            <Crosshair className="mt-0.5 size-4 shrink-0 text-fg-subtle" />
            <span>
              Open the camera or choose an image, then investigate a frame. The investigation
              explains where visible pollution is in the frame, why it matters, and what to do next —
              from what the detector actually returns.
            </span>
          </div>
        </DashboardCard>
      )}
    </div>
  );
}
