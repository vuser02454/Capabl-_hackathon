/**
 * DIAGNOSTIC ONLY — the waste pipeline with every stage laid open.
 *
 * Temporary. It exists because a wrong final label looks identical whichever stage produced it,
 * and there are five candidates: detection, cropping, preprocessing, classification, taxonomy.
 * Each panel below is one stage, shown as what that stage actually produced rather than as a
 * summary of it.
 *
 * The two crop images are deliberately separate. `crop` is the region cut from the photograph;
 * `model input` is the exact tensor the network consumed with normalisation inverted. If the crop
 * looks right and the model input does not, the fault is preprocessing — a distinction that
 * disappears the moment you show only one of them.
 */
import { Bug, Camera, ImageUp, Loader2, TriangleAlert } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import { cn } from '../../lib/format';
import { isAbortError, toAppError } from '../../services/errors';
import type { WasteDebugDetection, WasteDebugRun } from '../../types/agents';
import { Button } from '../ui/Button';
import { CameraCapture, cameraSupported } from '../ui/CameraCapture';
import { DashboardCard } from '../ui/DashboardCard';

function Stage({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="mb-1.5 text-[10px] font-medium tracking-wider text-fg-subtle uppercase">{title}</p>
      {children}
    </div>
  );
}

function Shot({ src, caption }: { src?: string; caption: string }) {
  if (!src) return <p className="text-[11px] text-fg-subtle">{caption}: not produced</p>;
  return (
    <figure className="min-w-0">
      <img src={src} alt={caption} className="w-full rounded-lg border border-black/10 bg-ink-950" />
      <figcaption className="mt-1 text-[10px] text-fg-subtle">{caption}</figcaption>
    </figure>
  );
}

function DetectionBlock({ detection }: { detection: WasteDebugDetection }) {
  const { detector, classifier, reported, taxonomy } = detection;
  // The gate is the interesting case: the network answered, and the pipeline declined to use it.
  const withheld = classifier.class !== null && reported.classification === null;

  return (
    <div className="rounded-xl border border-black/[0.07] bg-black/[0.02] p-3">
      <p className="mb-2 font-mono text-[10px] text-fg-subtle">{detection.id}</p>

      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1.4fr]">
        <Stage title="Exact crop">
          <Shot src={detection.cropImage} caption="region cut from the photo" />
        </Stage>
        <Stage title="Exact model input">
          <Shot src={detection.modelInputImage} caption="tensor fed to the network" />
        </Stage>

        <div className="space-y-2 text-xs">
          <Stage title="Detection (YOLO)">
            <p className="text-fg">
              {detector.class}{' '}
              <span className="text-fg-muted tabular">{Math.round(detector.confidence * 100)}%</span>
            </p>
            <p className="font-mono text-[10px] text-fg-subtle">
              [{detector.bbox.map((v) => Math.round(v)).join(', ')}]
            </p>
          </Stage>

          <Stage title="Classifier (raw argmax)">
            {classifier.class ? (
              <>
                <p className="text-fg">
                  {classifier.class}{' '}
                  <span className="text-fg-muted tabular">
                    {Math.round((classifier.confidence ?? 0) * 100)}%
                  </span>
                </p>
                {classifier.top5 && (
                  <ul className="mt-1 space-y-0.5">
                    {classifier.top5.map((entry) => (
                      <li key={entry.class} className="flex items-center gap-1.5 text-[10px]">
                        <span className="w-28 shrink-0 truncate text-fg-subtle">{entry.class}</span>
                        <span className="h-1 flex-1 overflow-hidden rounded-full bg-black/[0.06]">
                          <span
                            className="block h-full rounded-full bg-brand/70"
                            style={{ width: `${Math.max(1, entry.confidence * 100)}%` }}
                          />
                        </span>
                        <span className="w-8 text-right text-fg-subtle tabular">
                          {Math.round(entry.confidence * 100)}%
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <p className="text-fg-subtle">the classifier did not run on this crop</p>
            )}
          </Stage>

          <Stage title="Taxonomy lookup">
            {taxonomy ? (
              <p className="text-fg-muted">
                {taxonomy.lookedUp} → {taxonomy.category ?? '—'}
                {taxonomy.handling && <span className="text-fg-subtle"> · {taxonomy.handling}</span>}
              </p>
            ) : (
              <p className="text-fg-subtle">not looked up</p>
            )}
          </Stage>

          <Stage title="Final (what the API returned)">
            <p className={cn('font-medium', withheld ? 'text-risk-moderate' : 'text-fg')}>
              {reported.classification ?? reported.segregation}
              <span className="ml-1.5 text-[10px] font-normal text-fg-subtle">[{reported.status}]</span>
            </p>
            {withheld && (
              <p className="mt-1 text-[10px] text-fg-subtle">
                Withheld by a gate, not a model failure. {reported.message}
              </p>
            )}
          </Stage>
        </div>
      </div>
    </div>
  );
}

export function WasteDebugPanel() {
  const { api } = useSettings();
  const [run, setRun] = useState<WasteDebugRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const analyze = useCallback(
    async (file: File | Blob) => {
      setBusy(true);
      setError(null);
      setRun(null);
      try {
        setRun(await api.debugWaste(file));
      } catch (cause) {
        if (!isAbortError(cause)) setError(toAppError(cause).message);
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  return (
    <DashboardCard
      title="Waste debug"
      subtitle="Diagnostic only — every pipeline stage, from the real run"
      icon={Bug}
      iconColor="#fbbf24"
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-xl text-xs text-fg-muted">
            Runs the production pipeline and records each stage as it happens. Use it to tell a
            detector failure from a classifier failure — they produce the same wrong label.
          </p>
          <div className="flex flex-wrap gap-2">
            {cameraSupported() && (
              <Button size="sm" variant="secondary" icon={Camera} disabled={busy} onClick={() => setCameraOpen(true)}>
                Take Photo
              </Button>
            )}
            <Button size="sm" variant="primary" icon={ImageUp} loading={busy} onClick={() => fileRef.current?.click()}>
              Debug Image
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void analyze(file);
                event.target.value = '';
              }}
            />
          </div>
        </div>

        <CameraCapture
          open={cameraOpen}
          onClose={() => setCameraOpen(false)}
          onCapture={(file) => {
            setCameraOpen(false);
            void analyze(file);
          }}
          title="Photograph the waste"
          hint="Frame the object, then capture"
          fileName="waste-debug"
        />

        {error && (
          <p className="flex items-start gap-1.5 text-[11px] text-risk-moderate">
            <TriangleAlert className="mt-px size-3 shrink-0" />
            <span>{error}</span>
          </p>
        )}

        {busy && (
          <p className="flex items-center gap-2 text-xs text-fg-muted">
            <Loader2 className="size-3.5 animate-spin text-brand" /> Recording every stage…
          </p>
        )}

        {run && !busy && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Stage title="Original image">
                <Shot src={run.originalImage} caption={run.sourceFile} />
              </Stage>
              <Stage title="YOLO detection only">
                <Shot
                  src={run.detectorAnnotatedImage}
                  caption={`${run.rawDetections} raw box(es) — no classifier output shown`}
                />
              </Stage>
            </div>

            {/* An empty detection list is the single most informative debug result there is: it
                means the failure is stage 1, and nothing downstream ever ran. */}
            {run.detections.length === 0 ? (
              <p className="rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2.5 text-xs text-fg-muted">
                <span className="font-medium text-risk-moderate">The detector found nothing.</span>{' '}
                No crop, no classification and no taxonomy lookup happened, so the fault is stage 1.
                Nothing downstream can be blamed for this image.
              </p>
            ) : (
              <div className="space-y-3">
                {run.detections.map((detection) => (
                  <DetectionBlock key={detection.id} detection={detection} />
                ))}
              </div>
            )}

            <p className="text-[10px] text-fg-subtle">
              Artefacts written to <span className="font-mono">runs/debug_waste/</span>.
            </p>
          </>
        )}
      </div>
    </DashboardCard>
  );
}
