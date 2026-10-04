export type StepActionType = 'understand' | 'plan' | 'tool' | 'observe' | 'respond';
export type StepStatusType = 'executed' | 'confirmation_required' | 'blocked' | 'error' | 'completed' | 'repeated_call' | 'pending';

export interface AgentStep {
  step: number;
  action: StepActionType | string;
  tool?: string;
  arguments?: Record<string, unknown>;
  permission?: 'automatic' | 'confirmation_required' | 'blocked' | string;
  status: StepStatusType;
  error?: string;
  confirmation_id?: string;
  result?: unknown;
}

export interface ActivityTimelineItem {
  id: string;
  stepNumber?: number;
  type: 'understand' | 'plan' | 'tool' | 'observe' | 'confirmation_required' | 'completed' | 'blocked' | 'error';
  label: string;
  toolName?: string;
  status: StepStatusType;
  detail?: string;
  arguments?: Record<string, unknown>;
  result?: unknown;
  timestamp?: string;
}

export interface ConfirmationDetails {
  confirmation_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  summary?: string;
  status: 'pending' | 'approved' | 'rejected' | 'executed' | 'error';
  result?: unknown;
  message?: string;
}
