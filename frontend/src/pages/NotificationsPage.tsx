/**
 * The notification centre — one component, two audiences.
 *
 * The split is a data boundary, not a rendering choice: the admin and worker endpoints return
 * different shapes, and a worker's shape simply has no sender, report id, GPS accuracy or
 * extracted risk factors in it. So there is nothing here to hide — the fields a worker may not
 * see never arrive.
 *
 * The admin side is also the composer. An announcement sent here is a MESSAGE: it does not enter
 * routing. Only a published safety alert does, and the panel says so where the send button is,
 * because "I told the workers" and "I changed their routes" are different acts.
 */
import { Bell, BellOff, CheckCheck, Loader2, Megaphone, Send, Users } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Button } from '../components/ui/Button';
import { DashboardCard } from '../components/ui/DashboardCard';
import { Chip } from '../components/ui/primitives';
import { useNavigation } from '../context/NavigationContext';
import { useRole } from '../context/RoleContext';
import { useSettings } from '../context/SettingsContext';
import type { AdminNotification, WorkerDirectory, WorkerNotification } from '../types/safety';

const EMPLOYEE_KEY = 'ecosentinel.employeeId.v1';

const TYPE_LABEL: Record<string, string> = {
  REPORT_SUBMITTED: 'New report',
  ANNOUNCEMENT: 'Announcement',
  DIRECT_MESSAGE: 'Message',
  SAFETY_ALERT: 'Safety alert',
  WORKER_MESSAGE: 'From a colleague',
};

const SEVERITY_TONE: Record<string, string> = {
  HIGH: 'border-risk-high/25 bg-risk-high/10 text-risk-high',
  MEDIUM: 'border-risk-moderate/25 bg-risk-moderate/10 text-risk-moderate',
  LOW: 'border-risk-low/25 bg-risk-low/10 text-risk-low',
};

function remembered(): string {
  try {
    return window.localStorage.getItem(EMPLOYEE_KEY) ?? '';
  } catch {
    return '';
  }
}

export function NotificationsPage() {
  const { role } = useRole();
  return role === 'worker' ? <WorkerNotifications /> : <AdminNotifications />;
}

// --- admin --------------------------------------------------------------------------------

function AdminNotifications() {
  const { api } = useSettings();
  const { navigate } = useNavigation();
  const [items, setItems] = useState<AdminNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api.adminNotifications();
      setItems(body.notifications);
      setUnread(body.unreadCount);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load notifications.');
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  const open = async (item: AdminNotification) => {
    if (!item.read) {
      try {
        await api.adminMarkNotificationRead(item.id);
        await load();
      } catch { /* reading is a convenience; the list still works */ }
    }
    if (item.reportId != null) navigate('admin-reports');
  };

  return (
    <div className="space-y-4">
      <DashboardCard
        title="Notifications"
        subtitle={unread > 0 ? `${unread} unread` : 'All caught up'}
        icon={unread > 0 ? Bell : BellOff}
        iconColor={unread > 0 ? '#dc2626' : '#64748b'}
        actions={
          <Button size="sm" variant="ghost" icon={CheckCheck} loading={busy}
                  disabled={unread === 0}
                  onClick={async () => {
                    setBusy(true);
                    try { await api.adminMarkAllNotificationsRead(); await load(); }
                    finally { setBusy(false); }
                  }}>
            Mark all read
          </Button>
        }
      >
        {error && <p className="mb-2 text-xs text-risk-high">{error}</p>}
        {items.length === 0 && <p className="text-sm text-fg-muted">No notifications yet.</p>}

        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item.id}>
              <button type="button" onClick={() => void open(item)}
                      className={`w-full rounded-lg border px-3 py-2.5 text-left transition hover:border-brand/30 ${
                        item.read ? 'border-black/[0.06] bg-black/[0.02]'
                                  : 'border-brand/25 bg-brand/[0.05]'}`}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-[13px] font-semibold text-fg">
                    {!item.read && <span className="size-1.5 rounded-full bg-brand" aria-label="unread" />}
                    {item.title}
                  </span>
                  {item.severity && (
                    <span className={`rounded-full border px-2 py-0.5 text-[9.5px] font-semibold tracking-wider uppercase ${SEVERITY_TONE[item.severity] ?? ''}`}>
                      {item.severity}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-fg-muted">{item.message}</p>

                {Array.isArray(item.metadata?.hazards) && (item.metadata.hazards as string[]).length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {(item.metadata.hazards as string[]).slice(0, 4).map((hazard) => (
                      <Chip key={hazard}>{hazard}</Chip>
                    ))}
                  </div>
                )}

                <p className="mt-1 font-mono text-[10px] text-fg-subtle">
                  {TYPE_LABEL[item.type] ?? item.type}
                  {item.senderEmployeeId && ` · ${item.senderEmployeeId}`}
                  {item.reportId != null && ` · SR-${item.reportId}`}
                  {item.locationSource && ` · ${item.locationSource}`}
                  {item.gpsAccuracy != null && ` · ±${Math.round(item.gpsAccuracy)} m`}
                  {` · ${item.createdAt.slice(0, 16).replace('T', ' ')}`}
                </p>
              </button>
            </li>
          ))}
        </ul>
      </DashboardCard>

      <Composer onSent={() => void load()} />
    </div>
  );
}

function Composer({ onSent }: { onSent: () => void }) {
  const { api } = useSettings();
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [severity, setSeverity] = useState('MEDIUM');
  const [targets, setTargets] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    if (!title.trim() || !message.trim()) {
      setError('A title and a message are both required.');
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const employeeIds = targets.split(',').map((t) => t.trim()).filter(Boolean);
      const body = await api.adminSendNotification({
        title: title.trim(), message: message.trim(), severity,
        employeeIds: employeeIds.length ? employeeIds : undefined,
      });
      setResult(`Sent to ${body.delivery === 'broadcast' ? 'all workers' : `${body.count} worker(s)`}.`);
      setTitle('');
      setMessage('');
      setTargets('');
      onSent();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not send.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <DashboardCard title="Send to workers" subtitle="Broadcast, or target specific employee IDs"
                   icon={Megaphone} iconColor="#7c3aed">
      <div className="space-y-2">
        <input value={title} onChange={(e) => setTitle(e.target.value)}
               placeholder="Title" aria-label="Notification title"
               className="w-full rounded-lg border border-black/[0.08] bg-black/[0.02] px-3 py-2 text-xs text-fg outline-none focus:border-brand/40" />
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3}
                  placeholder="Message" aria-label="Notification message"
                  className="w-full resize-y rounded-lg border border-black/[0.08] bg-black/[0.02] px-3 py-2 text-xs text-fg outline-none focus:border-brand/40" />
        <div className="flex flex-wrap gap-2">
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}
                  aria-label="Severity"
                  className="rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand/40">
            <option value="LOW">LOW</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="HIGH">HIGH</option>
          </select>
          <input value={targets} onChange={(e) => setTargets(e.target.value)}
                 placeholder="Employee IDs, comma separated — blank sends to everyone"
                 aria-label="Target employee IDs"
                 className="min-w-0 flex-1 rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand/40" />
          <Button size="sm" variant="primary" icon={busy ? Loader2 : Send} loading={busy}
                  onClick={() => void send()}>Send</Button>
        </div>
      </div>

      {result && <p className="mt-2 text-[11.5px] text-risk-low">{result}</p>}
      {error && <p className="mt-2 text-[11.5px] text-risk-high">{error}</p>}

      {/* The distinction that matters: this is a message, not a hazard. */}
      <p className="mt-2 text-[10.5px] leading-relaxed text-fg-subtle">
        This sends a message to workers. It does <strong>not</strong> affect routing — only a
        published safety alert does, from the hotspot review screen.
      </p>
    </DashboardCard>
  );
}

// --- worker -------------------------------------------------------------------------------

function WorkerNotifications() {
  const { api } = useSettings();
  const [employeeId, setEmployeeId] = useState(remembered);
  const [items, setItems] = useState<WorkerNotification[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (id: string) => {
    const trimmed = id.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const body = await api.workerNotifications(trimmed);
      setItems(body.notifications);
      setUnread(body.unreadCount);
      setNote(body.note ?? '');
      try { window.localStorage.setItem(EMPLOYEE_KEY, trimmed); } catch { /* optional */ }
    } catch (cause) {
      setItems(null);
      setError(cause instanceof Error ? cause.message : 'Could not load notifications.');
    } finally {
      setBusy(false);
    }
  }, [api]);

  useEffect(() => {
    const id = remembered();
    if (id) void load(id);
  }, [load]);

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <DashboardCard
        title="Notifications"
        subtitle={unread > 0 ? `${unread} unread` : 'From the safety team'}
        icon={unread > 0 ? Bell : BellOff}
        iconColor={unread > 0 ? '#dc2626' : '#64748b'}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <input value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}
                   onKeyDown={(e) => { if (e.key === 'Enter') void load(employeeId); }}
                   placeholder="Employee ID" aria-label="Employee ID"
                   className="w-36 rounded-lg border border-black/[0.08] bg-black/[0.02] px-2.5 py-1.5 text-xs text-fg outline-none focus:border-brand/40" />
            <Button size="sm" variant="ghost" loading={busy}
                    onClick={() => void load(employeeId)}>Load</Button>
          </div>
        }
      >
        {error && <p className="mb-2 text-xs text-risk-high">{error}</p>}
        {items === null && !error && (
          <p className="text-sm text-fg-muted">Enter your employee ID to see your notifications.</p>
        )}
        {items?.length === 0 && <p className="text-sm text-fg-muted">No notifications yet.</p>}

        <ul className="space-y-1.5">
          {items?.map((item) => (
            <li key={item.id}>
              <button type="button"
                      onClick={async () => {
                        if (item.read) return;
                        try {
                          await api.workerMarkNotificationRead(employeeId.trim(), item.id);
                          await load(employeeId);
                        } catch { /* reading is a convenience */ }
                      }}
                      className={`w-full rounded-lg border px-3 py-2.5 text-left transition ${
                        item.read ? 'border-black/[0.06] bg-black/[0.02]'
                                  : 'border-brand/25 bg-brand/[0.05] hover:border-brand/40'}`}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-[13px] font-semibold text-fg">
                    {!item.read && <span className="size-1.5 rounded-full bg-brand" aria-label="unread" />}
                    {item.title}
                  </span>
                  {item.severity && (
                    <span className={`rounded-full border px-2 py-0.5 text-[9.5px] font-semibold tracking-wider uppercase ${SEVERITY_TONE[item.severity] ?? ''}`}>
                      {item.severity}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-fg-muted">{item.message}</p>
                <p className="mt-1 font-mono text-[10px] text-fg-subtle">
                  {TYPE_LABEL[item.type] ?? item.type}
                  {/* Only a message a person chose to send carries a sender. A report
                      notification never reaches a worker, so this can never reveal a reporter. */}
                  {item.senderEmployeeId
                    ? ` · from ${item.senderName ?? item.senderEmployeeId}`
                    : ' · Safety team'}
                  {` · ${item.createdAt.slice(0, 16).replace('T', ' ')}`}
                </p>
              </button>
            </li>
          ))}
        </ul>

        {note && (
          <p className="mt-3 rounded-lg border border-black/[0.06] bg-black/[0.02] px-3 py-2 text-[10.5px] leading-relaxed text-fg-subtle">
            {note}
          </p>
        )}
      </DashboardCard>

      {employeeId.trim() && (
        <WorkerComposer employeeId={employeeId.trim()} onSent={() => void load(employeeId)} />
      )}
    </div>
  );
}

/**
 * A worker writing to the safety team, or to a colleague.
 *
 * The admin is pre-selected because it is the common case and the safe one. Choosing a colleague
 * is a deliberate extra act, and the panel says what it costs: the recipient sees who wrote to
 * them. That is a real change from how reporting works — a report stays anonymous to other
 * workers — so it is stated at the point of choosing rather than discovered afterwards.
 */
function WorkerComposer({ employeeId, onSent }: { employeeId: string; onSent: () => void }) {
  const { api } = useSettings();
  const [directory, setDirectory] = useState<WorkerDirectory | null>(null);
  const [toAdmin, setToAdmin] = useState(true);
  const [colleagues, setColleagues] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setDirectory(await api.workerDirectory(employeeId));
      } catch {
        /* the admin option still works without the colleague list */
      }
    })();
  }, [api, employeeId]);

  const toggle = (id: string) =>
    setColleagues((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);

  const send = async () => {
    if (!title.trim() || !message.trim()) {
      setError('A title and a message are both required.');
      return;
    }
    if (!toAdmin && colleagues.length === 0) {
      setError('Choose the safety team or at least one colleague.');
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body = await api.workerSendNotification({
        employeeId, title: title.trim(), message: message.trim(),
        toAdmin, recipientEmployeeIds: colleagues,
      });
      const parts = [
        body.sentToAdmin ? 'the safety team' : null,
        body.sentToColleagues > 0 ? `${body.sentToColleagues} colleague(s)` : null,
      ].filter(Boolean);
      setResult(`Sent to ${parts.join(' and ')}.`);
      setTitle('');
      setMessage('');
      setColleagues([]);
      onSent();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not send the message.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <DashboardCard title="Send a message" subtitle="To the safety team, or to a colleague"
                   icon={Send} iconColor="#2563eb">
      <div className="space-y-2">
        <input value={title} onChange={(e) => setTitle(e.target.value)}
               placeholder="Subject" aria-label="Message subject"
               className="w-full rounded-lg border border-black/[0.08] bg-black/[0.02] px-3 py-2 text-xs text-fg outline-none focus:border-brand/40" />
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3}
                  placeholder="Message" aria-label="Message body"
                  className="w-full resize-y rounded-lg border border-black/[0.08] bg-black/[0.02] px-3 py-2 text-xs text-fg outline-none focus:border-brand/40" />

        <label className="flex items-center gap-2 text-[12px] text-fg">
          <input type="checkbox" checked={toAdmin} onChange={(e) => setToAdmin(e.target.checked)}
                 aria-label="Send to the safety team" className="size-3.5 accent-current" />
          Safety team
        </label>

        {directory && directory.colleagues.length > 0 && (
          <div className="rounded-lg border border-black/[0.06] bg-black/[0.02] p-2.5">
            <p className="eyebrow mb-1.5 flex items-center gap-1.5">
              <Users className="size-3" /> Colleagues
            </p>
            <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto">
              {directory.colleagues.map((person) => (
                <button key={person.employeeId} type="button"
                        onClick={() => toggle(person.employeeId)}
                        aria-pressed={colleagues.includes(person.employeeId)}
                        className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                          colleagues.includes(person.employeeId)
                            ? 'border-brand/40 bg-brand/[0.12] text-fg'
                            : 'border-black/[0.08] bg-black/[0.02] text-fg-muted hover:text-fg'}`}>
                  {person.employeeId} · {person.name}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex justify-end">
          <Button size="sm" variant="primary" icon={busy ? Loader2 : Send} loading={busy}
                  onClick={() => void send()}>Send</Button>
        </div>
      </div>

      {result && <p className="mt-2 text-[11.5px] text-risk-low">{result}</p>}
      {error && <p className="mt-2 text-[11.5px] text-risk-high">{error}</p>}

      {/* The posture change, stated where the choice is made. */}
      <p className="mt-2 text-[10.5px] leading-relaxed text-fg-subtle">
        {directory?.note
          ?? 'Messaging a colleague shows them your employee ID. Safety reports stay anonymous to other workers — this is separate from reporting.'}
      </p>
    </DashboardCard>
  );
}
