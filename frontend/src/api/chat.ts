import { request } from './client';
import {
  ChatRequestPayload,
  ChatResponsePayload,
  AgentRunResponsePayload,
  ConfirmRequestPayload,
  ConfirmResponsePayload,
} from '../types/api';

/**
 * Standard conversational chat with memory and session context.
 * Consumes: POST /api/chat
 */
export async function sendChatMessage(
  payload: ChatRequestPayload
): Promise<ChatResponsePayload> {
  return request<ChatResponsePayload>('/api/chat', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Bounded multi-step autonomous agent run with tool execution and confirmation handling.
 * Consumes: POST /api/agent/run
 */
export async function runAgent(
  payload: ChatRequestPayload
): Promise<AgentRunResponsePayload> {
  return request<AgentRunResponsePayload>('/api/agent/run', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Confirm or reject a pending tool execution.
 * Consumes: POST /api/agent/confirm
 */
export async function confirmAgentAction(
  payload: ConfirmRequestPayload
): Promise<ConfirmResponsePayload> {
  return request<ConfirmResponsePayload>('/api/agent/confirm', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
