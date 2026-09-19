/**
 * In-browser camera capture, with optional continuous frame scanning.
 *
 * Opens the device camera with getUserMedia, shows a live preview and hands back a still frame
 * as a File — the same shape an <input type="file"> would produce, so callers treat a captured
 * photo and a picked photo identically.
 *
 * When `onFrame` is supplied the preview is also sampled on an interval and each frame handed to
 * the caller, which is how the live contamination scan works. Sampling never overlaps: a new
 * frame is only taken once the previous one has been dealt with, so a slow backend throttles the
 * scan instead of queueing work behind it.
 *
 * getUserMedia needs a secure context (https, or localhost in development). When it is
 * unavailable or the user blocks the permission, this says so and the caller can fall back to
 * the file picker instead of leaving the user with a dead button.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { Camera, RefreshCw, TriangleAlert, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Button } from './Button';

export const cameraSupported = () =>
  typeof navigator !== 'undefined' && typeof navigator.mediaDevices?.getUserMedia === 'function';

interface CameraCaptureProps {
  open: boolean;
  onClose: () => void;
  onCapture: (file: File) => void;
  title?: string;
  hint?: string;
  /** Base name for the produced file, e.g. "water" -> water-1738…​.jpg */
  fileName?: string;
  /**
   * Called with a sampled preview frame every `scanIntervalMs`. The next sample waits for the
   * returned promise, so a slow consumer slows the scan rather than piling up requests.
   */
  onFrame?: (frame: Blob) => void | Promise<void>;
  scanIntervalMs?: number;
  /** Rendered over the preview — the live scan verdict. */
  scanOverlay?: ReactNode;
}

export function CameraCapture({
  open,
  onClose,
  onCapture,
  title = 'Take a photo',
  hint,
  fileName = 'capture',
  onFrame,
  scanIntervalMs = 2000,
  scanOverlay,
}: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [facing, setFacing] = useState<'environment' | 'user'>('environment');
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setReady(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    if (!cameraSupported()) {
      setError('This browser cannot open a camera here. Cameras need HTTPS (or localhost) — use "Choose photo" instead.');
      return;
    }

    setError(null);
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: facing }, audio: false })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          void videoRef.current.play().catch(() => undefined);
        }
        setReady(true);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        const name = cause instanceof DOMException ? cause.name : '';
        setError(
          name === 'NotAllowedError'
            ? 'Camera permission was denied. Allow camera access in your browser, or use "Choose photo".'
            : name === 'NotFoundError'
              ? 'No camera was found on this device. Use "Choose photo" instead.'
              : 'The camera could not be started. Use "Choose photo" instead.',
        );
      });

    return () => {
      cancelled = true;
      stop();
    };
  }, [open, facing, stop]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  /** Draw the current preview frame to a JPEG blob. `scale` shrinks it for cheap scan frames. */
  const grab = useCallback(
    (quality: number, scale = 1): Promise<Blob | null> =>
      new Promise((resolve) => {
        const video = videoRef.current;
        if (!video) return resolve(null);
        const width = Math.round(video.videoWidth * scale);
        const height = Math.round(video.videoHeight * scale);
        if (!width || !height) return resolve(null);

        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext('2d');
        if (!context) return resolve(null);
        context.drawImage(video, 0, 0, width, height);
        canvas.toBlob(resolve, 'image/jpeg', quality);
      }),
    [],
  );

  // Continuous scan. `scanning` guards against overlapping samples; the interval is cleared on
  // close, on camera error and on unmount, so nothing keeps sampling a stopped stream.
  const scanningRef = useRef(false);
  useEffect(() => {
    if (!open || !ready || !onFrame || error) return;
    let cancelled = false;

    const tick = async () => {
      if (cancelled || scanningRef.current) return;
      scanningRef.current = true;
      try {
        const frame = await grab(0.7, 0.5);
        if (frame && !cancelled) await onFrame(frame);
      } catch {
        /* one bad sample must not stop the scan */
      } finally {
        scanningRef.current = false;
      }
    };

    void tick();
    const timer = window.setInterval(() => void tick(), scanIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [open, ready, onFrame, error, grab, scanIntervalMs]);

  const capture = async () => {
    if (!ready) return;
    setBusy(true);
    const blob = await grab(0.92);
    setBusy(false);
    if (!blob) {
      setError('The photo could not be saved. Try again, or use "Choose photo".');
      return;
    }
    onCapture(new File([blob], `${fileName}-${Date.now()}.jpg`, { type: 'image/jpeg' }));
    onClose();
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[80] grid place-items-center bg-ink-950/80 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          role="dialog"
          aria-modal="true"
          aria-label={title}
        >
          <motion.div
            className="glass w-full max-w-lg overflow-hidden"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="flex items-start justify-between gap-3 px-5 pt-4">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold tracking-tight text-fg">{title}</h3>
                {hint && <p className="mt-0.5 text-xs text-fg-subtle">{hint}</p>}
              </div>
              <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close camera">
                <X className="size-4" />
              </Button>
            </header>

            <div className="px-5 pt-3 pb-5">
              <div className="relative aspect-[4/3] w-full overflow-hidden rounded-xl border border-white/[0.06] bg-ink-950">
                <video
                  ref={videoRef}
                  className="size-full object-cover"
                  playsInline
                  muted
                  autoPlay
                  aria-label="Live camera preview"
                />
                {!ready && !error && (
                  <div className="absolute inset-0 grid place-items-center text-xs text-fg-subtle">Starting camera…</div>
                )}
                {scanOverlay && ready && !error && (
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 p-2">{scanOverlay}</div>
                )}
                {error && (
                  <div className="absolute inset-0 grid place-items-center px-6 text-center">
                    <p className="flex flex-col items-center gap-2 text-xs text-fg-muted">
                      <TriangleAlert className="size-5 text-risk-moderate" />
                      {error}
                    </p>
                  </div>
                )}
              </div>

              <div className="mt-4 flex items-center justify-between gap-3">
                <Button
                  size="sm"
                  variant="ghost"
                  icon={RefreshCw}
                  disabled={!!error}
                  onClick={() => setFacing((current) => (current === 'environment' ? 'user' : 'environment'))}
                >
                  Flip camera
                </Button>
                <Button variant="primary" icon={Camera} loading={busy} disabled={!ready || !!error} onClick={() => void capture()}>
                  Capture photo
                </Button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
