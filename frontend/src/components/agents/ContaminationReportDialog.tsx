/**
 * Confirmation dialog for a citizen contamination report.
 *
 * This is the consent gate. Everything the report will contain — coordinates, place, the match
 * evidence and its reliability caveat — is shown BEFORE anything is sent, because the report is
 * the one thing in this app that transmits a precise location off the device.
 *
 * The result is reported exactly as the backend describes it: `recorded` means it was saved to the
 * backend's own log and nothing reached an authority. The dialog never upgrades that into
 * "reported" language, and always offers copy/download so the user can send it themselves.
 */
import { AnimatePresence, motion } from 'framer-motion';
import { Check, Copy, Download, MapPin, Send, TriangleAlert, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../../context/ToastContext';
import { toAppError } from '../../services/errors';
import type {
  ContaminationReportReceipt,
  ContaminationReportRequest,
  ReportLocation,
  WaterDatasetMatch,
} from '../../types/agents';
import { Button } from '../ui/Button';

interface ReportDialogProps {
  open: boolean;
  onClose: () => void;
  location: ReportLocation | null;
  match: WaterDatasetMatch;
  photo: string | null;
  source: 'upload' | 'camera';
  waterRiskLevel?: 'LOW' | 'MODERATE' | 'HIGH' | null;
  waterRiskScore?: number | null;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-1">
      <dt className="shrink-0 text-fg-subtle">{label}</dt>
      <dd className="min-w-0 text-right text-fg-muted">{children}</dd>
    </div>
  );
}

export function ContaminationReportDialog({
  open,
  onClose,
  location,
  match,
  photo,
  source,
  waterRiskLevel,
  waterRiskScore,
}: ReportDialogProps) {
  const { api, settings } = useSettings();
  const { notify } = useToast();
  const [note, setNote] = useState('');
  const [contact, setContact] = useState('');
  const [sending, setSending] = useState(false);
  const [receipt, setReceipt] = useState<ContaminationReportReceipt | null>(null);

  useEffect(() => {
    if (open) setReceipt(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const place =
    location?.displayName ??
    [location?.neighbourhood, location?.city, location?.state, location?.country].filter(Boolean).join(', ');

  const submit = async () => {
    if (!location) return;
    const request: ContaminationReportRequest = {
      location,
      match,
      observedAt: new Date().toISOString(),
      source,
      note: note.trim() || null,
      contact: contact.trim() || null,
      waterRiskLevel: waterRiskLevel ?? null,
      waterRiskScore: waterRiskScore ?? null,
      photo,
    };
    setSending(true);
    try {
      const result = await api.submitContaminationReport(request);
      setReceipt(result);
      notify({
        tone: result.status === 'forwarded' ? 'success' : result.status === 'recorded' ? 'info' : 'warning',
        title: `Report ${result.reference}`,
        description: result.message,
      });
    } catch (error) {
      const appError = toAppError(error);
      notify({ tone: 'error', title: appError.title, description: appError.message });
    } finally {
      setSending(false);
    }
  };

  const copy = async () => {
    if (!receipt) return;
    try {
      await navigator.clipboard.writeText(receipt.summary);
      notify({ tone: 'success', title: 'Report copied', description: 'Paste it into an email or complaint form.' });
    } catch {
      notify({ tone: 'error', title: 'Could not copy', description: 'Select the report text and copy it manually.' });
    }
  };

  const download = () => {
    if (!receipt) return;
    const blob = new Blob([receipt.summary], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${receipt.reference}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[85] grid place-items-center overflow-y-auto bg-ink-950/80 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          role="dialog"
          aria-modal="true"
          aria-label="Report contaminated water"
        >
          <motion.div
            className="glass my-auto w-full max-w-xl overflow-hidden"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="flex items-start justify-between gap-3 px-5 pt-4">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold tracking-tight text-fg">
                  {receipt ? `Report ${receipt.reference}` : 'Report this to the authorities?'}
                </h3>
                <p className="mt-0.5 text-xs text-fg-subtle">
                  {receipt ? 'What happened to your report' : 'Review exactly what will be sent before confirming'}
                </p>
              </div>
              <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close">
                <X className="size-4" />
              </Button>
            </header>

            <div className="max-h-[70vh] overflow-y-auto px-5 pt-3 pb-5">
              {receipt ? (
                <>
                  <div
                    className={
                      receipt.status === 'forwarded'
                        ? 'rounded-xl border border-risk-low/30 bg-risk-low/[0.08] px-3 py-3'
                        : receipt.status === 'recorded'
                          ? 'rounded-xl border border-info/30 bg-info/[0.08] px-3 py-3'
                          : 'rounded-xl border border-risk-moderate/30 bg-risk-moderate/[0.08] px-3 py-3'
                    }
                  >
                    <p className="flex items-start gap-2 text-[12.5px] text-fg-muted">
                      {receipt.status === 'forwarded' ? (
                        <Check className="mt-px size-4 shrink-0 text-risk-low" />
                      ) : (
                        <TriangleAlert className="mt-px size-4 shrink-0 text-risk-moderate" />
                      )}
                      <span>{receipt.message}</span>
                    </p>
                  </div>
                  <pre className="mt-3 max-h-64 overflow-auto rounded-xl border border-white/[0.06] bg-ink-950/60 p-3 text-[11px] leading-relaxed whitespace-pre-wrap text-fg-muted">
                    {receipt.summary}
                  </pre>
                  <div className="mt-4 flex flex-wrap justify-end gap-2">
                    <Button size="sm" icon={Copy} onClick={() => void copy()}>
                      Copy report
                    </Button>
                    <Button size="sm" icon={Download} onClick={download}>
                      Download
                    </Button>
                    <Button size="sm" variant="primary" onClick={onClose}>
                      Done
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
                    <p className="flex items-center gap-1.5 text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">
                      <MapPin className="size-3" /> Location that will be sent
                    </p>
                    {location ? (
                      <dl className="mt-1.5 text-xs">
                        <Row label="Coordinates">
                          <span className="tabular">
                            {location.latitude.toFixed(5)}, {location.longitude.toFixed(5)}
                          </span>
                        </Row>
                        {location.accuracyM != null && (
                          <Row label="Accuracy">±{Math.round(location.accuracyM)} m</Row>
                        )}
                        {place && <Row label="Place">{place}</Row>}
                      </dl>
                    ) : (
                      <p className="mt-1.5 text-xs text-risk-moderate">
                        No location yet — a report needs one. Allow location access first.
                      </p>
                    )}
                  </div>

                  <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
                    <p className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">Evidence</p>
                    <dl className="mt-1.5 text-xs">
                      <Row label="Resembles">{match.matchedLabel ?? 'No confident match'}</Row>
                      {match.similarity != null && (
                        <Row label="Similarity">
                          <span className="tabular">{(match.similarity * 100).toFixed(0)}%</span>
                        </Row>
                      )}
                      <Row label="Photo">{photo ? 'attached' : 'not attached'}</Row>
                      <Row label="Source">{source === 'camera' ? 'live camera frame' : 'uploaded photo'}</Row>
                    </dl>
                    {match.caveat && (
                      <p className="mt-2 border-t border-white/[0.06] pt-2 text-[10.5px] leading-relaxed text-fg-subtle">
                        This caveat is included in the report itself: {match.caveat}
                      </p>
                    )}
                  </div>

                  <label className="mt-3 block">
                    <span className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">
                      What did you see? (optional)
                    </span>
                    <textarea
                      value={note}
                      onChange={(event) => setNote(event.target.value.slice(0, 1000))}
                      rows={3}
                      placeholder="e.g. Thick foam along the eastern bank, strong smell since Tuesday."
                      className="mt-1 w-full rounded-xl border border-white/[0.08] bg-white/[0.02] px-3 py-2 text-xs text-fg outline-none placeholder:text-fg-subtle focus:border-brand/50"
                    />
                  </label>

                  <label className="mt-2 block">
                    <span className="text-[10.5px] font-medium tracking-wider text-fg-subtle uppercase">
                      Contact for follow-up (optional)
                    </span>
                    <input
                      value={contact}
                      onChange={(event) => setContact(event.target.value.slice(0, 200))}
                      placeholder="email or phone"
                      className="mt-1 w-full rounded-xl border border-white/[0.08] bg-white/[0.02] px-3 py-2 text-xs text-fg outline-none placeholder:text-fg-subtle focus:border-brand/50"
                    />
                  </label>

                  <p className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[10.5px] leading-relaxed text-fg-subtle">
                    Confirming stores this report — including your exact coordinates — in the backend's report log.
                    It is forwarded onwards only if this deployment has a destination configured; otherwise nothing
                    is transmitted and you can copy or download the report to send yourself.
                    {settings.demoMode && ' Demo Mode is on, so there is no backend to receive this.'}
                  </p>

                  <div className="mt-4 flex flex-wrap justify-end gap-2">
                    <Button size="sm" variant="ghost" onClick={onClose}>
                      Not now
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      icon={Send}
                      loading={sending}
                      disabled={!location || settings.demoMode}
                      onClick={() => void submit()}
                    >
                      Confirm and submit
                    </Button>
                  </div>
                </>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
