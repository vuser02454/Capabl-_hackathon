/**
 * The notification centre, both sides.
 *
 * One page serves two audiences, and the split is a data boundary rather than a rendering choice:
 * the worker endpoint simply does not return report evidence, so there is nothing here to hide.
 * What the UI owns, and what these tests check, is that the two composers say what they cost.
 *
 * The attribution rule is the subtle one. A worker-sent message shows its sender, because an
 * anonymous message cannot be weighed or answered. A safety REPORT stays anonymous to other
 * workers — the report notification is addressed to the admin and never reaches a worker at all.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RoleProvider } from '../context/RoleContext';
import { SettingsProvider } from '../context/SettingsContext';
import { NavigationProvider } from '../context/NavigationContext';
import { NotificationsPage } from './NotificationsPage';

const ROLE_KEY = 'ecosentinel.role.v1';
const EMPLOYEE_KEY = 'ecosentinel.employeeId.v1';

const ADMIN_FEED = {
  notifications: [{
    id: 1, type: 'REPORT_SUBMITTED', title: 'New HIGH report from EMP005',
    message: 'Exposed live wire near the wet floor.', severity: 'HIGH',
    createdAt: '2026-09-20T11:05:00+00:00', read: false, readAt: null,
    latitude: 12.97, longitude: 77.59, radiusMeters: null, expiresAt: null,
    senderEmployeeId: 'EMP005', recipientEmployeeId: null, reportId: 209,
    gpsAccuracy: 9.5, locationSource: 'browser_gps',
    metadata: { hazards: ['Electrical hazard', 'Wet surface'] },
  }],
  count: 1, unreadCount: 1,
};

const WORKER_FEED = {
  notifications: [{
    id: 4, type: 'WORKER_MESSAGE', title: 'Spare harness',
    message: 'Left one in the store for you.', severity: null,
    createdAt: '2026-09-20T11:10:00+00:00', read: false, readAt: null,
    latitude: null, longitude: null, radiusMeters: null, expiresAt: null,
    senderEmployeeId: 'EMP001', senderName: 'Worker 001',
  }],
  count: 1, unreadCount: 1,
  note: 'Announcements from the safety team.',
};

const DIRECTORY = {
  admin: { label: 'Safety Admin', employeeId: 'ADMIN001' },
  colleagues: [
    { employeeId: 'EMP002', name: 'Worker 002', department: 'Warehouse' },
    { employeeId: 'EMP003', name: 'Worker 003', department: 'Logistics' },
  ],
  note: 'Messaging a colleague shows them your employee ID. Safety reports stay anonymous to '
      + 'other workers — this is separate from reporting.',
};

/** Route each stubbed request by URL, and record what was posted. */
function stubFetch(routes: Record<string, unknown>) {
  const calls: Array<{ url: string; body: Record<string, unknown> | null }> = [];
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    const match = Object.keys(routes).find((path) => url.includes(path));
    return Promise.resolve({
      ok: true, status: 200,
      text: () => Promise.resolve(JSON.stringify(match ? routes[match] : {})),
    } as Response);
  }));
  return calls;
}

function renderAs(role: 'worker' | 'admin') {
  try {
    window.localStorage.setItem(ROLE_KEY, role);
    if (role === 'worker') window.localStorage.setItem(EMPLOYEE_KEY, 'EMP005');
  } catch { /* private browsing */ }
  return render(
    <SettingsProvider>
      <NavigationProvider>
        <RoleProvider>
          <NotificationsPage />
        </RoleProvider>
      </NavigationProvider>
    </SettingsProvider>,
  );
}

const posted = (calls: Array<{ url: string; body: Record<string, unknown> | null }>, path: string) =>
  calls.find((c) => c.url.includes(path) && c.body)?.body;

beforeEach(() => {
  try { window.localStorage.clear(); } catch { /* optional */ }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// --- admin ---------------------------------------------------------------------------------

describe('the admin notification centre', () => {
  it('shows an incoming report with the evidence needed to act', async () => {
    stubFetch({ '/api/admin/notifications': ADMIN_FEED });
    renderAs('admin');

    await waitFor(() => expect(screen.getByText(/New HIGH report from EMP005/)).toBeTruthy());
    expect(screen.getByText(/SR-209/)).toBeTruthy();
    expect(screen.getByText('Electrical hazard')).toBeTruthy();
    expect(screen.getByText(/±10 m/)).toBeTruthy();
  });

  it('shows the unread count', async () => {
    stubFetch({ '/api/admin/notifications': ADMIN_FEED });
    renderAs('admin');
    await waitFor(() => expect(screen.getByText('1 unread')).toBeTruthy());
  });

  it('sends a broadcast when no employee IDs are given', async () => {
    const calls = stubFetch({
      '/api/admin/notifications/send': { ids: [9], count: 1, delivery: 'broadcast', note: 'x' },
      '/api/admin/notifications': ADMIN_FEED,
    });
    renderAs('admin');

    await waitFor(() => expect(screen.getByLabelText('Notification title')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Notification title'), { target: { value: 'Inspection' } });
    fireEvent.change(screen.getByLabelText('Notification message'), { target: { value: 'Friday 0900.' } });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    await waitFor(() => expect(posted(calls, '/notifications/send')).toBeTruthy());
    expect(posted(calls, '/notifications/send')?.employee_ids).toBeNull();
  });

  it('targets named workers when IDs are given', async () => {
    const calls = stubFetch({
      '/api/admin/notifications/send': { ids: [9], count: 1, delivery: 'targeted', note: 'x' },
      '/api/admin/notifications': ADMIN_FEED,
    });
    renderAs('admin');

    await waitFor(() => expect(screen.getByLabelText('Target employee IDs')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Notification title'), { target: { value: 'Re-file' } });
    fireEvent.change(screen.getByLabelText('Notification message'), { target: { value: 'Incomplete.' } });
    fireEvent.change(screen.getByLabelText('Target employee IDs'), { target: { value: 'EMP002, EMP003' } });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    await waitFor(() => expect(posted(calls, '/notifications/send')).toBeTruthy());
    expect(posted(calls, '/notifications/send')?.employee_ids).toEqual(['EMP002', 'EMP003']);
  });

  it('states that an announcement does not affect routing', async () => {
    stubFetch({ '/api/admin/notifications': ADMIN_FEED });
    renderAs('admin');
    // The distinction between telling workers and changing their routes. Matched on a
    // contiguous fragment: "does not affect routing" is split by a <strong> in the markup.
    await waitFor(() =>
      expect(screen.getByText(/only a published safety alert does/i)).toBeTruthy());
  });
});

// --- worker --------------------------------------------------------------------------------

describe('the worker notification centre', () => {
  it('attributes a message a colleague chose to send', async () => {
    stubFetch({ '/api/worker/notifications': WORKER_FEED, '/api/worker/directory': DIRECTORY });
    renderAs('worker');

    await waitFor(() => expect(screen.getByText('Spare harness')).toBeTruthy());
    // An unattributable message cannot be weighed, answered, or reported as misuse.
    expect(screen.getByText(/from Worker 001/)).toBeTruthy();
  });

  it('shows the safety team as the sender when there is no person', async () => {
    stubFetch({
      '/api/worker/notifications': {
        ...WORKER_FEED,
        notifications: [{ ...WORKER_FEED.notifications[0], type: 'ANNOUNCEMENT',
                          senderEmployeeId: null, senderName: null, title: 'Inspection Friday' }],
      },
      '/api/worker/directory': DIRECTORY,
    });
    renderAs('worker');
    await waitFor(() => expect(screen.getByText(/Safety team/)).toBeTruthy());
  });

  it('offers the safety team pre-selected and colleagues opt-in', async () => {
    stubFetch({ '/api/worker/notifications': WORKER_FEED, '/api/worker/directory': DIRECTORY });
    renderAs('worker');

    await waitFor(() => expect(screen.getByLabelText('Send to the safety team')).toBeTruthy());
    // The common case and the safe one is the default.
    expect((screen.getByLabelText('Send to the safety team') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole('button', { name: /EMP002 · Worker 002/ })).toBeTruthy();
  });

  it('sends to the safety team', async () => {
    const calls = stubFetch({
      '/api/worker/notifications/send': { ids: [7], count: 1, sentToAdmin: true,
                                          sentToColleagues: 0, note: 'x' },
      '/api/worker/notifications': WORKER_FEED, '/api/worker/directory': DIRECTORY,
    });
    renderAs('worker');

    await waitFor(() => expect(screen.getByLabelText('Message subject')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Message subject'), { target: { value: 'Bay 7 wet' } });
    fireEvent.change(screen.getByLabelText('Message body'), { target: { value: 'Still not dry.' } });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    await waitFor(() => expect(posted(calls, '/worker/notifications/send')).toBeTruthy());
    const body = posted(calls, '/worker/notifications/send');
    expect(body?.to_admin).toBe(true);
    expect(body?.employee_id).toBe('EMP005');
  });

  it('sends to a chosen colleague', async () => {
    const calls = stubFetch({
      '/api/worker/notifications/send': { ids: [7], count: 1, sentToAdmin: false,
                                          sentToColleagues: 1, note: 'x' },
      '/api/worker/notifications': WORKER_FEED, '/api/worker/directory': DIRECTORY,
    });
    renderAs('worker');

    await waitFor(() => expect(screen.getByRole('button', { name: /EMP002/ })).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Send to the safety team'));   // uncheck admin
    fireEvent.click(screen.getByRole('button', { name: /EMP002/ }));
    fireEvent.change(screen.getByLabelText('Message subject'), { target: { value: 'Harness' } });
    fireEvent.change(screen.getByLabelText('Message body'), { target: { value: 'In the store.' } });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    await waitFor(() => expect(posted(calls, '/worker/notifications/send')).toBeTruthy());
    const body = posted(calls, '/worker/notifications/send');
    expect(body?.to_admin).toBe(false);
    expect(body?.recipient_employee_ids).toEqual(['EMP002']);
  });

  it('refuses to send with no recipient at all', async () => {
    const calls = stubFetch({ '/api/worker/notifications': WORKER_FEED,
                              '/api/worker/directory': DIRECTORY });
    renderAs('worker');

    await waitFor(() => expect(screen.getByLabelText('Message subject')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Send to the safety team'));
    fireEvent.change(screen.getByLabelText('Message subject'), { target: { value: 'x' } });
    fireEvent.change(screen.getByLabelText('Message body'), { target: { value: 'y' } });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    await waitFor(() => expect(screen.getByText(/safety team or at least one colleague/i)).toBeTruthy());
    expect(posted(calls, '/worker/notifications/send')).toBeUndefined();
  });

  it('says that messaging a colleague reveals your ID, and that reports do not', async () => {
    stubFetch({ '/api/worker/notifications': WORKER_FEED, '/api/worker/directory': DIRECTORY });
    renderAs('worker');
    // Stated where the choice is made, not discovered afterwards.
    await waitFor(() => expect(screen.getByText(/shows them your employee ID/i)).toBeTruthy());
    expect(screen.getByText(/reports stay anonymous to other workers/i)).toBeTruthy();
  });

  it('never renders report evidence, because the worker payload has none', async () => {
    const { container } = render(<div />);
    cleanup();
    stubFetch({ '/api/worker/notifications': WORKER_FEED, '/api/worker/directory': DIRECTORY });
    renderAs('worker');

    await waitFor(() => expect(screen.getByText('Spare harness')).toBeTruthy());
    const text = document.body.textContent?.toLowerCase() ?? '';
    for (const term of ['sr-', 'gps accuracy', 'risk factor', 'browser_gps']) {
      expect(text).not.toContain(term);
    }
    expect(container).toBeTruthy();
  });
});
