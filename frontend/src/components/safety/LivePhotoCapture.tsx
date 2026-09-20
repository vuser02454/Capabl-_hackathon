/**
 * Live photo evidence for a safety report.
 *
 * The camera stream starts only when the worker presses the button — `getUserMedia` is never
 * called on mount, so the permission prompt is always the result of a deliberate act. A denial
 * ends the camera and nothing else: the report is still filed, without a photo. That is why this
 * component owns no part of the submit path and reports its result upward as an optional file.
 *
 * The photo is evidence of what was seen, NOT of where it was seen. EXIF is deliberately ignored:
 * the authoritative geotag is the fix the worker confirmed in the app, which the report carries
 * separately. Many browsers strip EXIF from a canvas capture anyway, and a photo's embedded
 * position can be stale or absent — relying on it would put hazards in the wrong place.
 */
import { Camera, RefreshCw, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '../ui/Button';

export interface CapturedPhoto {
  file: File;
  previewUrl: string;
  capturedAt: string;
}

type Phase = 'idle' | 'starting' | 'streaming' | 'captured' | 'denied' | 'unsupported' | 'error';

const MESSAGES: Partial<Record<Phase, string>> = {
  denied: 'Camera permission was denied. You can still submit the report without a photo.',
  unsupported: 'This browser does not provide camera access. You can still submit without a photo.',
  error: 'The camera could not be started. You can still submit the report without a photo.',
};

export function LivePhotoCapture({
  photo,
  onChange,
}: {
  photo: CapturedPhoto | null;
  onChange: (next: CapturedPhoto | null) => void;
}) {
  const [phase, setPhase] = useState<Phase>('idle');
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  // A live camera left running after the worker navigates away is both a battery and a privacy
  // problem, so the stream is torn down on unmount without exception.
  useEffect(() => stop, [stop]);

  const start = async () => {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setPhase('unsupported');
      return;
    }
    setPhase('starting');
    try {
      // `environment` asks for the rear camera, which is the one pointed at the hazard.
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } }, audio: false,
      });
      streamRef.current = stream;
      setPhase('streaming');
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => { /* autoplay policies vary; the frame still renders */ });
      }
    } catch (cause) {
      const name = cause instanceof DOMException ? cause.name : '';
      setPhase(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'error');
      stop();
    }
  };

  const capture = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) {
        setPhase('error');
        return;
      }
      const capturedAt = new Date().toISOString();
      const file = new File([blob], `report-${Date.now()}.jpg`, { type: 'image/jpeg' });
      onChange({ file, previewUrl: URL.createObjectURL(file), capturedAt });
      setPhase('captured');
      stop();
    }, 'image/jpeg', 0.88);
  };

  const discard = () => {
    if (photo) URL.revokeObjectURL(photo.previewUrl);
    onChange(null);
    setPhase('idle');
  };

  return (
    <div className="space-y-2">
      {phase === 'idle' && !photo && (
        <Button size="sm" variant="ghost" icon={Camera} onClick={() => void start()}>
          Take Live Photo
        </Button>
      )}

      {(phase === 'starting' || phase === 'streaming') && (
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <video ref={videoRef} playsInline muted
                 className="max-h-64 w-full rounded-lg bg-black object-contain" />
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="primary" icon={Camera} disabled={phase !== 'streaming'}
                    onClick={capture}>
              Capture
            </Button>
            <Button size="sm" variant="ghost" icon={X} onClick={() => { stop(); setPhase('idle'); }}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {photo && (
        <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-3">
          <img src={photo.previewUrl} alt="Captured evidence"
               className="max-h-64 w-full rounded-lg object-contain" />
          <p className="mt-1.5 text-[11px] text-fg-muted">
            Live camera photo ✓ · captured {new Date(photo.capturedAt).toLocaleTimeString()}
          </p>
          {/* Stated on the screen where the photo is taken, so the provenance rule is visible
              to the person it affects rather than buried in the admin view. */}
          <p className="mt-0.5 text-[10.5px] text-fg-subtle">
            The report's location comes from the fix you confirm below, not from the photo.
          </p>
          <Button className="mt-2" size="sm" variant="ghost" icon={RefreshCw} onClick={discard}>
            Retake
          </Button>
        </div>
      )}

      {MESSAGES[phase] && (
        <p role="status" className="rounded-lg border border-risk-moderate/25 bg-risk-moderate/[0.07] px-3 py-2 text-xs text-risk-moderate">
          {MESSAGES[phase]}
        </p>
      )}
    </div>
  );
}
