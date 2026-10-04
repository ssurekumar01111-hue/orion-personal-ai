import { request } from './client';
import { SessionItem, SessionMessage } from '../types/api';

/**
 * Creates a new conversation session.
 * Consumes: POST /api/sessions
 */
export async function createSession(title: string = 'New Session'): Promise<SessionItem> {
  return request<SessionItem>(`/api/sessions?title=${encodeURIComponent(title)}`, {
    method: 'POST',
  });
}

/**
 * Lists recent conversation sessions.
 * Consumes: GET /api/sessions
 */
export async function listSessions(limit: number = 20): Promise<SessionItem[]> {
  const data = await request<{ sessions: SessionItem[] }>(`/api/sessions?limit=${limit}`);
  return data.sessions || [];
}

/**
 * Retrieves message history for a session.
 * Consumes: GET /api/sessions/{session_id}/messages
 */
export async function getSessionMessages(sessionId: string, limit: number = 50): Promise<SessionMessage[]> {
  const data = await request<{ session_id: string; messages: SessionMessage[] }>(
    `/api/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}`
  );
  return data.messages || [];
}

/**
 * Deletes a session by ID.
 * Consumes: DELETE /api/sessions/{session_id}
 */
export async function deleteSession(sessionId: string): Promise<boolean> {
  const data = await request<{ deleted: boolean }>(
    `/api/sessions/${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' }
  );
  return Boolean(data.deleted);
}
