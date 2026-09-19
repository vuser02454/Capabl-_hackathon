/**
 * Real waste detection on a photo the user supplied.
 *
 * This exists because the Waste Agent's demo provider generates boxes from a seeded RNG — random
 * labels at random positions with confidences between 0.76 and 0.98, never looking at the image.
 * Shown next to a photograph of one bottle it produced "Metal can 0.91", "Textile 0.83" and
 * "Rubber 0.97" scattered across a bedroom, which is indistinguishable from a real result unless
 * you notice the word "simulated" in small text.
 *
 * Everything here comes from `POST /api/waste/segregate`: YOLO locates objects, the trained
 * classifier labels each crop. When the model finds nothing, this says so — an empty result is a
 * real answer and far more useful than a convincing invention.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { Camera, ImageUp, Loader2, ScanSearch, TriangleAlert } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import { isAbortError, toAppError } from '../../services/errors';
import { cn } from '../../lib/format';
import type { WasteSegregationResult } from '../../types/agents';
import { Button } from '../ui/Button';
import { CameraCapture, cameraSupported } from '../ui/CameraCapture';
import { DashboardCard } from '../ui/DashboardCard';

const SEGREGATION_STYLE: Record<string, string> = {
  biodegradable: 'text-risk-low border-risk-low/30 bg-risk-low/[0.08]',
  non_biodegradable: 'text-info border-info/30 bg-info/[0.08]',
  uncertain: 'text-fg-subtle border-black/10 bg-black/[0.03]',
};

const SEGREGATION_LABEL: Record<string, string> = {
  biodegradable: 'Biodegradable',
  non_biodegradable: 'Non-biodegradable',
  uncertain: 'Uncertain',
};

export function RealWasteDetection() {
  const { api } = useSettings();
  const [result, setResult] = useState<WasteSegregationResult | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  // Off by default: attribution costs a backward pass per detected object.
  const [explain, setExplain] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const analyze = useCallback(
    async (file: File | Blob) => {
      setBusy(true);
      setError(null);
      setResult(null);
      setActive(null);
      setImageUrl((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return URL.createObjectURL(file);
      });
      try {
        setResult(await api.segregateWaste(file, undefined, explain));
      } catch (cause) {
        if (!isAbortError(cause)) setError(toAppError(cause).message);
      } finally {
        setBusy(false);
      }
    },
    [api, explain],
  );

  const detections = result?.detections ?? [];

  return (
    <DashboardCard
      title="Real detection"
      subtitle="YOLO detection + trained waste classifier — not simulated"
      icon={ScanSearch}
      iconColor="#2563eb"
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-fg-muted">
            Analyses the photo with the actual models. Results come from what a model found — including
            nothing.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-fg-muted">
              <input
                type="checkbox"
                checked={explain}
                disabled={busy}
                onChange={(event) => setExplain(event.target.checked)}
                className="size-3.5 accent-brand"
              />
              Explain (Grad-CAM)
            </label>
            {cameraSupported() && (
              <Button size="sm" variant="secondary" icon={Camera} disabled={busy} onClick={() => setCameraOpen(true)}>
                Take Photo
              </Button>
            )}
            <Button size="sm" variant="primary" icon={ImageUp} loading={busy} onClick={() => fileRef.current?.click()}>
              Detect Waste
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
          fileName="waste"
        />

        {error && (
          <p className="flex items-start gap-1.5 text-[11px] text-risk-moderate">
            <TriangleAlert className="mt-px size-3 shrink-0" />
            <span>{error}</span>
          </p>
        )}

        <AnimatePresence>
          {busy && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 text-xs text-fg-muted"
            >
              <Loader2 className="size-3.5 animate-spin text-brand" /> Running detection and classification…
            </motion.p>
          )}
        </AnimatePresence>

        {imageUrl && !busy && (
          <div className="relative overflow-hidden rounded-xl border border-black/10">
            <img src={imageUrl} alt="Analysed photo" className="block w-full" />
            {detections.map((detection, index) => {
              if (!result?.imageWidth || !result?.imageHeight) return null;
              const [x1, y1, x2, y2] = detection.bbox;
              const selected = active === detection.id;
              return (
                <button
                  key={detection.id}
                  type="button"
                  onClick={() => setActive(selected ? null : detection.id)}
                  className={cn(
                    'absolute rounded-md border-2 transition',
                    selected ? 'border-brand bg-brand/20' : 'border-brand/70 hover:bg-brand/10',
                  )}
                  style={{
                    left: `${(x1 / result.imageWidth) * 100}%`,
                    top: `${(y1 / result.imageHeight) * 100}%`,
                    width: `${((x2 - x1) / result.imageWidth) * 100}%`,
                    height: `${((y2 - y1) / result.imageHeight) * 100}%`,
                  }}
                >
                  <span className="absolute -top-5 left-0 rounded bg-brand px-1 py-0.5 text-[9px] font-medium whitespace-nowrap text-ink-950">
                    #{index + 1} {detection.detectedObject}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {result && !busy && (
          <>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-fg-subtle">
              <span>Detector: <span className="text-fg-muted">{result.model ?? 'unavailable'}</span></span>
              <span>Objects: <span className="text-fg-muted tabular">{result.summary.totalObjects}</span></span>
              <span>Biodegradable: <span className="text-fg-muted tabular">{result.summary.biodegradable}</span></span>
              <span>Non-biodegradable: <span className="text-fg-muted tabular">{result.summary.nonBiodegradable}</span></span>
              <span>Uncertain: <span className="text-fg-muted tabular">{result.summary.uncertain}</span></span>
              {result.summary.duplicateBoxesMerged > 0 && (
                <span>
                  Merged duplicates: <span className="text-fg-muted tabular">{result.summary.duplicateBoxesMerged}</span>
                </span>
              )}
              {result.summary.nonWasteObjects > 0 && (
                <span>
                  Not waste: <span className="text-fg-muted tabular">{result.summary.nonWasteObjects}</span>
                </span>
              )}
            </div>

            {/* An empty result is a real answer, and saying so beats inventing a convincing one. */}
            {detections.length === 0 && (
              <p className="rounded-lg border border-black/[0.08] bg-black/[0.02] px-3 py-2.5 text-xs text-fg-muted">
                {result.status === 'ok'
                  ? 'The detector found no objects it recognises in this photo. That is not the same as "no waste is present".'
                  : `Detection did not run. ${result.message ?? ''}`}
              </p>
            )}

            {detections.length > 0 && (
              <ul className="space-y-1.5">
                {detections.map((detection, index) => {
                  const selected = active === detection.id;
                  return (
                    <li key={detection.id}>
                      <button
                        type="button"
                        onClick={() => setActive(selected ? null : detection.id)}
                        className={cn(
                          'w-full rounded-lg border px-3 py-2 text-left transition',
                          selected ? 'border-brand/40 bg-brand/[0.07]' : 'border-black/[0.06] bg-black/[0.02] hover:bg-black/[0.05]',
                        )}
                      >
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
                          <span className="font-mono text-[10px] text-fg-subtle">#{index + 1}</span>
                          {/* The two stages are shown separately: a COCO "cup" classified as
                              "metal_cans" is informative, not a contradiction to hide. */}
                          <span className="text-fg">
                            {detection.detectedObject}
                            <span className="text-fg-subtle"> · detection {Math.round(detection.detectionConfidence * 100)}%</span>
                          </span>
                          {detection.classification ? (
                            <span className="text-fg-muted">
                              → {detection.display ?? detection.classification}
                              <span className="text-fg-subtle">
                                {detection.labelSource === 'detector'
                                  ? ' · detector label'
                                  : ` · classification ${Math.round((detection.classificationConfidence ?? 0) * 100)}%`}
                              </span>
                            </span>
                          ) : detection.candidate ? (
                            <span className="text-fg-subtle">
                              → unconfirmed guess: {detection.candidate}
                            </span>
                          ) : (
                            <span className="text-fg-subtle">→ not classified</span>
                          )}
                          <span className={cn('ml-auto rounded border px-1.5 py-0.5 text-[9.5px]', SEGREGATION_STYLE[detection.segregation])}>
                            {SEGREGATION_LABEL[detection.segregation]}
                          </span>
                        </div>
                        {detection.alsoDetectedAs && detection.alsoDetectedAs.length > 0 && (
                          <p className="mt-1 text-[10.5px] text-fg-subtle">
                            The detector also labelled this same region {detection.alsoDetectedAs.join(', ')} —
                            counted once.
                          </p>
                        )}
                        {detection.message && (
                          <p className="mt-1 text-[10.5px] text-fg-subtle">{detection.message}</p>
                        )}
                        {selected && detection.environmentalNote && (
                          <p className="mt-1 text-[10.5px] text-fg-subtle">{detection.environmentalNote}</p>
                        )}
                        {/* Attribution: either the model's real gradients, or a stated absence.
                            There is no fallback image, by design. */}
                        {selected && detection.xai && (
                          <div className="mt-2 border-t border-black/[0.06] pt-2">
                            <p className="text-[10px] font-medium tracking-wider text-fg-subtle uppercase">
                              Why the classifier said this
                            </p>
                            {detection.xai.available && detection.xai.overlayImage ? (
                              <>
                                <img
                                  src={detection.xai.overlayImage}
                                  alt={`Grad-CAM attribution for ${detection.xai.targetClass ?? 'the prediction'}`}
                                  className="mt-1.5 w-full max-w-[220px] rounded-lg border border-black/10"
                                />
                                <p className="mt-1 text-[10.5px] text-fg-subtle">
                                  {detection.xai.method} over {detection.xai.layer}, computed at{' '}
                                  {detection.xai.attributionGrid} and upsampled — regional, not
                                  pixel-level. Warm areas are where the gradients for{' '}
                                  <span className="text-fg-muted">{detection.xai.targetClass}</span>{' '}
                                  came from.
                                </p>
                              </>
                            ) : (
                              <p className="mt-1 text-[10.5px] text-fg-subtle">
                                XAI unavailable — {detection.xai.message ?? 'attribution could not be computed.'}
                              </p>
                            )}
                          </div>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </div>
    </DashboardCard>
  );
}
