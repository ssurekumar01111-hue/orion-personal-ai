export type ProjectStatus = 'active' | 'paused' | 'completed' | 'archived' | string;
export type GoalStatus = 'active' | 'paused' | 'completed' | 'abandoned' | 'pending' | 'in_progress' | string;
export type TaskStatus = 'todo' | 'pending' | 'in_progress' | 'blocked' | 'completed' | 'cancelled' | string;
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent' | string;

export interface Project {
  id: number;
  name: string;
  description: string;
  path?: string | null;
  repository?: string | null;
  status: ProjectStatus;
  created_at?: string;
  updated_at?: string;
}

export interface Goal {
  id: number;
  title: string;
  description: string;
  status: GoalStatus;
  project_id?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface Task {
  id: number;
  title: string;
  description?: string;
  status: TaskStatus;
  priority: TaskPriority;
  project_id?: number | null;
  goal_id?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface Decision {
  id: number;
  decision: string;
  context: string;
  project_id?: number | null;
  created_at?: string;
}

export interface SkillWorkflowStep {
  tool: string;
  arguments: Record<string, unknown>;
}

export interface SkillWorkflow {
  steps: SkillWorkflowStep[];
}

export interface Skill {
  id: number;
  name: string;
  description: string;
  workflow: string | SkillWorkflow;
  created_at?: string;
  updated_at?: string;
}

export interface EpisodicMemory {
  id: number;
  content: string;
  category: string;
  importance: number;
  source_session?: string | null;
  project_id?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface SkillExecution {
  id: number;
  skill_id: number;
  session_id?: string | null;
  status: 'completed' | 'error' | 'blocked' | 'confirmation_required' | string;
  step_results: Array<{ step: number; tool: string; result?: unknown; error?: string }>;
  failure_reason?: string | null;
  duration_ms: number;
  created_at?: string;
}

export interface SkillProposal {
  id: number;
  skill_id: number;
  title: string;
  description: string;
  proposed_workflow: SkillWorkflow | string;
  rationale: string;
  status: 'pending' | 'approved' | 'rejected';
  created_at?: string;
  applied_at?: string | null;
}

export interface SkillVersion {
  id: number;
  skill_id: number;
  version_number: number;
  name: string;
  description: string;
  workflow: SkillWorkflow | string;
  change_summary: string;
  created_at?: string;
}

export interface LearningEvent {
  id: number;
  task_key: string;
  session_id?: string | null;
  user_objective: string;
  completion_status: 'success' | 'failed' | 'blocked' | 'pending_confirmation' | string;
  learned_memories_count: number;
  learned_decisions_count: number;
  task_updates_count: number;
  summary: string;
  details?: Record<string, unknown>;
  created_at?: string;
}

export interface PersonalModelSnapshot {
  projects: Project[];
  goals: Goal[];
  tasks: Task[];
  decisions?: Decision[];
  skills: Skill[];
}
