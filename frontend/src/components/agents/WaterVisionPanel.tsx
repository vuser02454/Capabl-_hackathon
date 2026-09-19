/**
 * Water Pollution Vision — the YOLO26 half of the Water Agent report.
 *
 * Deliberately presented as a separate block from the sensor readings. Visual detection counts
 * pollution objects in an image; it does not measure pH, turbidity, dissolved oxygen or
 * chemistry, and this panel never implies otherwise.
 *
 * Litter and other detected objects are counted under separate headings. The production detector
 * is a COCO model: in a river scene it reports people, boats and kites alongside any litter, and
 * this panel once listed all of them under "objects detected" beside a pollution risk. Both
 * numbers are shown — what the model saw, and what of that is litter.
 */
import { ScanSearch } from 'lucide-react';
import { AGENT_META } from './agentMeta';
import { DashboardCard } from '../ui/DashboardCard';
import { Chip } from '../ui/primitives';
import { cn, pct } from '../../lib/format';
import { RISK_STYLES } from '../../lib/risk';
import type { WaterVisionReport } from '../../types/agents';

/** Human-readable reason for every non-ok status, so "no result" is never silent. */
const STATUS_COPY: Record<string, string> = {
  not_run: 'No image analysed. Upload a water image to run visual pollution detection.',
  model_not_configured: 'YOLO26 model is not configured on the backend.',
  unavailable: 'Visual detection was unavailable for this run.',
};

export function WaterVisionPanel({ vision, waterQualityScore, combinedScore }: {
  vision: WaterVisionReport;
  waterQualityScore?: number | null;
  combinedScore?: number;
}) {
  const color = AGENT_META.water.color;
  const level = vision.visualLevel ? RISK_STYLES[vision.visualLevel] : null;

  // Litter and everything else are counted separately and labelled separately. The backend sends
  // both; older payloads without the split fall back to deriving it from the detections, and only
  // as a last resort to the raw total — the one number that must never sit under a pollution
  // heading on its own.
  const litterFromDetections = vision.detections.filter(
    (d) => d.semanticCategory === 'visible_surface_litter',
  );
  const litterCount = vision.pollutionObjects ?? litterFromDetections.length;
  const otherCount = vision.totalObjects - litterCount;
  const litterClasses = Object.entries(
    vision.pollutionCounts ??
      litterFromDetections.reduce<Record<string, number>>((acc, d) => {
        acc[d.className] = (acc[d.className] ?? 0) + 1;
        return acc;
      }, {}),
  ).sort((a, b) => b[1] - a[1]);
  const otherClasses = Object.entries(vision.objectCounts)
    .filter(([name]) => !litterClasses.some(([litter]) => litter === name))
    .sort((a, b) => b[1] - a[1]);

  return (
    <DashboardCard
      title="Water Pollution Vision"
      subtitle="Visual detection of pollution objects — separate from the measured water-quality parameters"
      icon={ScanSearch}
      iconColor={color}
      actions={<Chip color={color}>{vision.model ?? 'YOLO26 Nano'}</Chip>}
    >
      {vision.status !== 'ok' ? (
        <p className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-3 text-[12.5px] text-fg-muted">
          {vision.message ?? STATUS_COPY[vision.status] ?? 'Visual detection did not run.'}
        </p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
              <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">
                Visible litter
              </p>
              <p className="tabular mt-1 text-lg font-semibold text-fg">{litterCount}</p>
              <p className="text-[10.5px] text-fg-subtle">
                of {vision.totalObjects} object{vision.totalObjects === 1 ? '' : 's'} detected
                {vision.confidenceThreshold != null && ` at ≥${pct(vision.confidenceThreshold)}%`}
              </p>
            </div>
            <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
              <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">Visual signal</p>
              <p className={cn('mt-1 text-lg font-semibold', level ? level.text : 'text-fg')}>
                {vision.visualLevel ?? '—'}
              </p>
              {vision.visualScore != null && (
                <p className="text-[10.5px] text-fg-subtle">density {pct(vision.visualScore)}%</p>
              )}
            </div>
            <div className="rounded-xl border border-black/[0.06] bg-black/[0.02] px-3 py-2.5">
              <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">Contribution</p>
              {/* Shown only when the visual signal actually moved the combined number. */}
              {waterQualityScore != null && combinedScore != null ? (
                <>
                  <p className="tabular mt-1 text-lg font-semibold text-fg">
                    {pct(waterQualityScore)}% → {pct(combinedScore)}%
                  </p>
                  <p className="text-[10.5px] text-fg-subtle">measured → combined water risk</p>
                </>
              ) : (
                <>
                  <p className="mt-1 text-lg font-semibold text-fg">None</p>
                  <p className="text-[10.5px] text-fg-subtle">did not change the water risk</p>
                </>
              )}
            </div>
          </div>

          <div className="mt-3 border-t border-black/[0.06] pt-3">
            <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">
              Observed — visible litter
            </p>
            {litterClasses.length > 0 ? (
              <ul className="mt-1.5 space-y-1.5">
                {litterClasses.map(([name, count]) => (
                  <li key={name} className="flex items-baseline justify-between gap-3">
                    <span className="truncate text-[12.5px] text-fg-muted capitalize">
                      {name.replace(/_/g, ' ')}
                    </span>
                    <span className="tabular text-[13px] font-semibold text-fg">{count}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1.5 text-[12px] text-fg-muted">
                No visible litter was detected in this image.
              </p>
            )}
          </div>

          {/* Other objects are shown, not hidden: the detector did find them, and concealing them
              would misrepresent what the model did. They are simply not pollution. */}
          {otherClasses.length > 0 && (
            <div className="mt-3 border-t border-black/[0.06] pt-3">
              <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">
                Also detected — not counted as pollution
              </p>
              <ul className="mt-1.5 space-y-1.5">
                {otherClasses.map(([name, count]) => (
                  <li key={name} className="flex items-baseline justify-between gap-3">
                    <span className="truncate text-[12.5px] text-fg-subtle capitalize">
                      {name.replace(/_/g, ' ')}
                    </span>
                    <span className="tabular text-[13px] font-medium text-fg-muted">{count}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-1.5 text-[10.5px] text-fg-subtle">
                {otherCount} object{otherCount === 1 ? '' : 's'} the detector found that do not
                indicate litter. They do not affect the water risk score.
              </p>
            </div>
          )}

          <div className="mt-3 border-t border-black/[0.06] pt-3">
            <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">
              Not established
            </p>
            <p className="mt-1.5 text-[12px] text-fg-muted">
              Chemical contamination, pH, dissolved oxygen and potability. An image shows a surface
              condition; it cannot measure chemistry.
              {litterCount === 0 &&
                ' Absence of visible litter is not evidence that the water is clean.'}
            </p>
          </div>

          {vision.annotatedImage && (
            <img
              src={vision.annotatedImage}
              alt={`Annotated water image: ${litterCount} litter object${
                litterCount === 1 ? '' : 's'
              } of ${vision.totalObjects} detected`}
              className="mt-3 w-full rounded-xl border border-black/[0.06]"
            />
          )}

          <p className="mt-3 text-[10.5px] leading-relaxed text-fg-subtle">
            Visual detection only. pH, turbidity, temperature and TDS are measured by the water
            sensor/dataset shown above — a vision model cannot determine them.
          </p>
        </>
      )}
    </DashboardCard>
  );
}
