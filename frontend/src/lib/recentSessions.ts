/**
 * Sessions this browser has opened, most recent first.
 *
 * The server deliberately has no "list all sessions" endpoint: session IDs are
 * unguessable capabilities, and listing them would expose other users'
 * sessions.  Only IDs this browser created or opened are remembered here.
 */
const KEY = 'aap_recent_sessions';
const MAX = 12;

export interface RecentSessionRef {
  id: string;
  openedAt: string;
}

export function readRecentSessions(storage: Pick<Storage, 'getItem'> = localStorage): RecentSessionRef[] {
  try {
    const parsed = JSON.parse(storage.getItem(KEY) ?? '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item) => item && typeof item.id === 'string' && /^ses_[0-9a-f]{32}$/.test(item.id))
      .slice(0, MAX);
  } catch {
    return [];
  }
}

export function rememberSession(
  id: string,
  storage: Pick<Storage, 'getItem' | 'setItem'> = localStorage,
  now: Date = new Date(),
): RecentSessionRef[] {
  const next = [{ id, openedAt: now.toISOString() }, ...readRecentSessions(storage).filter((item) => item.id !== id)].slice(0, MAX);
  storage.setItem(KEY, JSON.stringify(next));
  return next;
}

export function forgetSession(id: string, storage: Pick<Storage, 'getItem' | 'setItem'> = localStorage): RecentSessionRef[] {
  const next = readRecentSessions(storage).filter((item) => item.id !== id);
  storage.setItem(KEY, JSON.stringify(next));
  return next;
}
