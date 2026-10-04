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
  created_at?: string;
}

export interface PersonalModelSnapshot {
  projects: Project[];
  goals: Goal[];
  tasks: Task[];
  decisions?: Decision[];
  skills: Skill[];
}
