import { AgentStep } from './agent';
import { Skill } from './personal';

export type ProviderType = 'nebius' | 'hermes';

export interface ChatRequestPayload {
  message: string;
  provider?: ProviderType;
  session_id?: string | null;
}

export interface ContextUsageInfo {
  memories_used?: number;
  memory_ids?: number[];
  messages_used?: number;
}

export interface ChatResponsePayload {
  session_id: string;
  provider: ProviderType;
  model: string;
  response: string;
  context?: ContextUsageInfo;
}

export interface AgentRunResponsePayload {
  session_id: string;
  response: string;
  provider: ProviderType;
  model?: string;
  steps: AgentStep[];
  tool_used?: string | null;
  tool_arguments?: Record<string, unknown> | null;
  tool_result?: unknown;
  permission_status?: string | null;
  confirmation_required?: boolean;
  confirmation_id?: string | null;
  confirmation_summary?: string | null;
}

export interface ConfirmRequestPayload {
  confirmation_id: string;
  approved: boolean;
  session_id?: string | null;
}

export interface ConfirmResponsePayload {
  status: 'executed' | 'rejected' | 'error';
  confirmation_id: string;
  tool: string;
  executed: boolean;
  message?: string;
  result?: unknown;
  provider?: ProviderType;
  model?: string;
}

export interface SessionItem {
  id: string;
  title: string;
  created_at: string;
  updated_at?: string;
}

export interface SessionMessage {
  id?: number;
  session_id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
}

export interface ProvidersResponse {
  providers: ProviderType[];
  default: ProviderType;
}

export interface ToolsResponse {
  tools: Array<{
    name: string;
    description: string;
    permission: 'automatic' | 'confirmation_required' | 'blocked' | string;
  }>;
}

export interface SkillsResponse {
  skills: Skill[];
}
