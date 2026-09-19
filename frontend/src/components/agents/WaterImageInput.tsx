/**
 * Water photo input for the Water Agent.
 *
 * Two ways in — take a photo with the device camera, or pick one already stored on the device
 * (drag & drop works too). While the camera is open its preview is scanned continuously against
 * the labelled reference dataset, so a contamination flag can appear without pressing anything.
 *
 * The photo feeds the VISUAL half of the Water Agent's report only: pH, turbidity, temperature and
 * TDS keep coming from the sensor/dataset readings.
 */
import { Camera, ImageUp, Images, Upload } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { useAnalysis } from '../../context/AnalysisContext';
import { useSettings } from '../../context/SettingsContext';
import { cn } from '../../lib/format';
import { MAX_UPLOAD_BYTES } from '../../services/providers/wasteDetectionSource';
import type { WaterDatasetMatch } from '../../types/agents';
import { Button } from '../ui/Button';
import { CameraCapture, cameraSupported } from '../ui/CameraCapture';
import { DashboardCard } from '../ui/DashboardCard';
import { AGENT_META } from './agentMeta';
import { ContaminationAlert, LiveScanBadge } from './ContaminationAlert';
import { DatasetMatchPanel } from './DatasetMatchPanel';

/** File/Blob -> data URI, so an evidence frame can travel inside a JSON report. */
function toDataUri(blob: Blob): Promise<string | null> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : null);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(blob);
  });
}

export function WaterImageInput() {
  const { state, pending, display, analyzeWaterImage } = useAnalysis();
  const { api, settings } = useSettings();
  const pickerRef = useRef<HTMLInputElement>(null);
  const nativeCameraRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [liveMatch, setLiveMatch] = useState<WaterDatasetMatch | null>(null);
  const [scanning, setScanning] = useState(false);
  // Evidence for a report: whichever frame produced the match currently on screen.
  const [evidence, setEvidence] = useState<string | null>(null);

  const running = state.phase === 'running';
  const photo = state.waterImage;
  const analysing = pending.water && state.runKind === 'image';
  const water = display.water;

  // Which verdict is on screen. A live camera verdict wins while the camera is open, and a
  // camera verdict that RAISED A FLAG outlives the camera closing — otherwise the alert, the
  // location and the report prompt would all vanish the moment the user shut the preview to read
  // them. Anything else falls back to the analysed photo's match.
  const heldFlag = !cameraOpen && liveMatch?.contaminated ? liveMatch : null;
  const activeMatch = cameraOpen ? liveMatch : (heldFlag ?? water?.datasetMatch ?? null);
  const activeSource: 'upload' | 'camera' = cameraOpen || heldFlag ? 'camera' : 'upload';

  // Live scanning needs the backend matcher; Demo Mode has no backend to ask.
  const scanDisabled = settings.demoMode ? 'Demo Mode — live scanning needs the backend' : undefined;

  const submit = async (file: File | undefined) => {
    if (!file) return;
    // A new photo supersedes any held live-camera verdict.
    setLiveMatch(null);
    setEvidence(await toDataUri(file));
    void analyzeWaterImage(file);
  };

  const scanFrame = useCallback(
    async (frame: Blob) => {
      if (settings.demoMode) return;
      setScanning(true);
      try {
        const result = await api.matchWaterFrame(frame);
        setLiveMatch(result);
        // Only keep a frame as evidence when it is the one that raised the flag.
        setEvidence(result.contaminated ? await toDataUri(frame) : null);
      } catch {
        // A dropped scan is not worth a toast every two seconds; the badge keeps the last verdict.
      } finally {
        setScanning(false);
      }
    },
    [api, settings.demoMode],
  );

  // Desktop browsers ignore the `capture` attribute, so use getUserMedia where it exists and
  // fall back to the native camera input (mobile) only when it does not.
  const takePhoto = () => {
    if (cameraSupported()) {
      setLiveMatch(null);
      setCameraOpen(true);
    } else {
      nativeCameraRef.current?.click();
    }
  };

  return (
    <>
      <DashboardCard
        title="Water photo"
        subtitle="Take a photo of the water body, or choose one from this device — matched against the reference dataset"
        icon={Camera}
        iconColor={AGENT_META.water.color}
        actions={
          <>
            <Button size="sm" variant="primary" icon={Camera} disabled={running} onClick={takePhoto}>
              Take photo
            </Button>
            <Button size="sm" icon={Images} disabled={running} onClick={() => pickerRef.current?.click()}>
              Choose photo
            </Button>
          </>
        }
      >
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            if (!running) void submit(event.dataTransfer.files?.[0]);
          }}
          className={cn(
            'relative grid min-h-44 place-items-center rounded-xl border border-dashed border-white/[0.1] bg-white/[0.02] p-3 transition',
            dragging && 'border-brand/60 ring-2 ring-brand/40',
          )}
        >
          {photo ? (
            <figure className="w-full">
              <img
                src={photo.url}
                alt={`Water photo submitted for analysis: ${photo.name}`}
                className="max-h-72 w-full rounded-lg object-contain"
              />
              <figcaption className="mt-2 flex items-center justify-between gap-3 text-[11px] text-fg-subtle">
                <span className="truncate">{photo.name}</span>
                <span className="shrink-0">{analysing ? 'Analysing…' : 'Submitted'}</span>
              </figcaption>
            </figure>
          ) : (
            <div className="px-4 text-center">
              <ImageUp className="mx-auto size-6 text-fg-subtle" />
              <p className="mt-2 text-xs text-fg-muted">
                Take a photo or choose one from your gallery — or drop a JPG, PNG or WebP here (max{' '}
                {MAX_UPLOAD_BYTES / 1024 / 1024} MB).
              </p>
            </div>
          )}
          {dragging && (
            <div className="absolute inset-0 grid place-items-center rounded-xl bg-ink-950/70 backdrop-blur-sm">
              <p className="flex items-center gap-2 text-sm font-medium text-brand">
                <Upload className="size-4" /> Drop photo to analyse
              </p>
            </div>
          )}
        </div>

        <input
          ref={pickerRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            void submit(file);
          }}
        />
        <input
          ref={nativeCameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            void submit(file);
          }}
        />

        <p className="mt-3 text-[10.5px] leading-relaxed text-fg-subtle">
          The photo adds a visual signal only. pH, turbidity, temperature and TDS are measured by the
          water sensor/dataset — a vision model cannot determine them, and the reference match never
          changes the risk score. This re-runs the Water Agent alone; re-run the area analysis for a
          fresh Coordinator assessment.
        </p>
      </DashboardCard>

      {activeMatch?.contaminated && (
        <ContaminationAlert
          match={activeMatch}
          photo={evidence}
          source={activeSource}
          waterRiskLevel={water?.riskLevel}
          waterRiskScore={water?.riskScore}
        />
      )}

      {activeMatch && activeMatch.status !== 'not_run' && <DatasetMatchPanel match={activeMatch} />}

      <CameraCapture
        open={cameraOpen}
        onClose={() => {
          setCameraOpen(false);
          // Keep a flag (and its evidence frame) so the alert survives closing the preview;
          // discard an unremarkable verdict so a stale "no match" never sits on the page.
          setLiveMatch((current) => (current?.contaminated ? current : null));
        }}
        onCapture={(file) => void submit(file)}
        title="Photograph the water"
        hint={
          scanDisabled
            ? 'Frame the water surface and shoreline where litter collects.'
            : 'Scanning every couple of seconds — capture when you want the full Water Agent analysis.'
        }
        fileName="water"
        onFrame={settings.demoMode ? undefined : scanFrame}
        scanOverlay={<LiveScanBadge match={liveMatch} scanning={scanning} disabled={scanDisabled} />}
      />
    </>
  );
}
