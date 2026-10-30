import { request } from './client';
import {
  Project,
  Goal,
  Task,
  Skill,
  EpisodicMemory,
  PersonalModelSnapshot,
  SkillExecution,
  SkillProposal,
  SkillVersion,
  LearningEvent,
} from '../types/personal';

/**
 * Fetch skills from backend.
 * Consumes: GET /api/skills
 */
export async function getSkills(limit: number = 50): Promise<Skill[]> {
  try {
    const data = await request<{ skills: Skill[] }>(`/api/skills?limit=${limit}`);
    return data.skills || [];
  } catch (err) {
    console.warn('Failed to fetch skills from /api/skills:', err);
    return [];
  }
}

/**
 * Fetch recent episodic memories.
 * Consumes: GET /api/memory/recent
 */
export async function getRecentMemories(limit: number = 20): Promise<EpisodicMemory[]> {
  try {
    const data = await request<{ memories: EpisodicMemory[] }>(`/api/memory/recent?limit=${limit}`);
    return data.memories || [];
  } catch (err) {
    console.warn('Failed to fetch memories from /api/memory/recent:', err);
    return [];
  }
}

/**
 * Returns full Personal Model snapshot from backend SQLite Personal Model.
 * Consumes: GET /api/personal/snapshot
 */
export async function getPersonalSnapshot(): Promise<PersonalModelSnapshot> {
  try {
    const data = await request<PersonalModelSnapshot>('/api/personal/snapshot');
    return {
      projects: data.projects || [],
      goals: data.goals || [],
      tasks: data.tasks || [],
      decisions: data.decisions || [],
      skills: data.skills || [],
    };
  } catch (err) {
    console.warn('Failed to fetch personal snapshot from /api/personal/snapshot:', err);
    return {
      projects: [],
      goals: [],
      tasks: [],
      decisions: [],
      skills: [],
    };
  }
}

/**
 * Fetch projects from the real Personal Model snapshot.
 */
export async function getProjects(): Promise<Project[]> {
  const snapshot = await getPersonalSnapshot();
  return snapshot.projects;
}

/**
 * Fetch goals from the real Personal Model snapshot.
 */
export async function getGoals(): Promise<Goal[]> {
  const snapshot = await getPersonalSnapshot();
  return snapshot.goals;
}

/**
 * Fetch tasks from the real Personal Model snapshot.
 */
export async function getTasks(): Promise<Task[]> {
  const snapshot = await getPersonalSnapshot();
  return snapshot.tasks;
}

/**
 * Delete a memory by ID.
 * Consumes: DELETE /api/memory/:id
 */
export async function deleteMemory(memoryId: number): Promise<boolean> {
  try {
    const res = await request<{ deleted: boolean }>(`/api/memory/${memoryId}`, {
      method: 'DELETE',
    });
    return res.deleted;
  } catch (err) {
    console.error('Failed to delete memory:', err);
    return false;
  }
}

/**
 * Fetch execution history for a skill.
 * Consumes: GET /api/skills/:skill_id/executions
 */
export async function getSkillExecutions(skillId: number, limit: number = 20): Promise<SkillExecution[]> {
  try {
    const res = await request<{ executions: SkillExecution[] }>(`/api/skills/${skillId}/executions?limit=${limit}`);
    return res.executions || [];
  } catch (err) {
    console.warn(`Failed to fetch executions for skill ${skillId}:`, err);
    return [];
  }
}

/**
 * Fetch proposed improvements for a skill.
 * Consumes: GET /api/skills/:skill_id/proposals
 */
export async function getSkillProposals(skillId: number, status?: string): Promise<SkillProposal[]> {
  try {
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    const res = await request<{ proposals: SkillProposal[] }>(`/api/skills/${skillId}/proposals${query}`);
    return res.proposals || [];
  } catch (err) {
    console.warn(`Failed to fetch proposals for skill ${skillId}:`, err);
    return [];
  }
}

/**
 * Approve a proposed skill improvement.
 * Consumes: POST /api/skills/:skill_id/proposals/:proposal_id/approve
 */
export async function approveSkillProposal(skillId: number, proposalId: number): Promise<{ status: string; skill?: Skill }> {
  return request<{ status: string; skill?: Skill }>(`/api/skills/${skillId}/proposals/${proposalId}/approve`, {
    method: 'POST',
  });
}

/**
 * Reject a proposed skill improvement.
 * Consumes: POST /api/skills/:skill_id/proposals/:proposal_id/reject
 */
export async function rejectSkillProposal(skillId: number, proposalId: number): Promise<{ status: string }> {
  return request<{ status: string }>(`/api/skills/${skillId}/proposals/${proposalId}/reject`, {
    method: 'POST',
  });
}

/**
 * Fetch versions of a skill.
 * Consumes: GET /api/skills/:skill_id/versions
 */
export async function getSkillVersions(skillId: number): Promise<SkillVersion[]> {
  try {
    const res = await request<{ versions: SkillVersion[] }>(`/api/skills/${skillId}/versions`);
    return res.versions || [];
  } catch (err) {
    console.warn(`Failed to fetch versions for skill ${skillId}:`, err);
    return [];
  }
}

/**
 * Rollback a skill to a previous version number.
 * Consumes: POST /api/skills/:skill_id/rollback/:version_number
 */
export async function rollbackSkill(skillId: number, versionNumber: number): Promise<{ status: string; skill?: Skill }> {
  return request<{ status: string; skill?: Skill }>(`/api/skills/${skillId}/rollback/${versionNumber}`, {
    method: 'POST',
  });
}

/**
 * Fetch system learning events.
 * Consumes: GET /api/learning/events
 */
export async function getLearningEvents(sessionId?: string, limit: number = 20): Promise<LearningEvent[]> {
  try {
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}&limit=${limit}` : `?limit=${limit}`;
    const res = await request<{ events: LearningEvent[] }>(`/api/learning/events${query}`);
    return res.events || [];
  } catch (err) {
    console.warn('Failed to fetch learning events:', err);
    return [];
  }
}
