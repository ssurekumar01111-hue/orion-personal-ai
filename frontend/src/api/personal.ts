import { request } from './client';
import { Project, Goal, Task, Skill, EpisodicMemory, PersonalModelSnapshot } from '../types/personal';

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
