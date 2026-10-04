import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ProjectsPanel } from '../components/personal/ProjectsPanel';
import { GoalsPanel } from '../components/personal/GoalsPanel';
import { TasksPanel } from '../components/personal/TasksPanel';
import { SkillsPanel } from '../components/personal/SkillsPanel';
import { MemoryPanel } from '../components/personal/MemoryPanel';
import { RightSidebar } from '../components/layout/RightSidebar';
import { Project, Goal, Task, Skill, EpisodicMemory } from '../types/personal';
import { getPersonalSnapshot, getProjects, getGoals, getTasks } from '../api/personal';

const mockBackendProjects: Project[] = [
  {
    id: 68,
    name: 'Separation Proj',
    description: 'Core separation project from SQLite',
    path: '/home/gfood/orion',
    repository: 'orion',
    status: 'active',
  },
];

const mockBackendGoals: Goal[] = [
  {
    id: 101,
    project_id: 68,
    title: 'Migrate to Real Backend Model',
    description: 'Ensure backend SQLite is single source of truth',
    status: 'active',
  },
];

const mockBackendTasks: Task[] = [
  {
    id: 201,
    project_id: 68,
    goal_id: 101,
    title: 'Verify snapshot endpoint returns real data',
    status: 'todo',
    priority: 'high',
  },
];

const mockSkills: Skill[] = [
  {
    id: 1,
    name: 'Repo Status Review',
    description: 'Inspect git and files',
    workflow: {
      steps: [
        { tool: 'git_status', arguments: {} },
        { tool: 'read_file', arguments: { path: 'README.md' } },
      ],
    },
  },
];

const mockMemories: EpisodicMemory[] = [
  {
    id: 1,
    content: 'User prefers dark console interface.',
    category: 'preference',
    importance: 4,
    created_at: new Date().toISOString(),
  },
];

describe('Personal Model Backend API and UI Panels', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  describe('API Layer (/api/personal/snapshot)', () => {
    it('fetches and returns real backend snapshot without mock fallback', async () => {
      const mockSnapshot = {
        projects: mockBackendProjects,
        goals: mockBackendGoals,
        tasks: mockBackendTasks,
        decisions: [],
        skills: mockSkills,
      };

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(JSON.stringify(mockSnapshot), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const snapshot = await getPersonalSnapshot();
      expect(snapshot.projects).toEqual(mockBackendProjects);
      expect(snapshot.projects[0].name).toBe('Separation Proj');
      expect(snapshot.goals[0].title).toBe('Migrate to Real Backend Model');
      expect(snapshot.tasks[0].title).toBe('Verify snapshot endpoint returns real data');

      // Verify no fabricated Orion demo data
      expect(snapshot.projects.some((p) => p.name === 'Orion Personal AI')).toBe(false);
      expect(snapshot.goals.some((g) => g.title === 'Phase 5A UI Shell')).toBe(false);
      expect(snapshot.tasks.some((t) => t.title === 'Implement 3-region responsive layout')).toBe(false);
    });

    it('getProjects, getGoals, getTasks consume getPersonalSnapshot without hardcoded fallback', async () => {
      const mockSnapshot = {
        projects: mockBackendProjects,
        goals: mockBackendGoals,
        tasks: mockBackendTasks,
        decisions: [],
        skills: [],
      };

      vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
        new Response(JSON.stringify(mockSnapshot), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );

      const projects = await getProjects();
      expect(projects).toEqual(mockBackendProjects);
      expect(projects[0].name).toBe('Separation Proj');

      const goals = await getGoals();
      expect(goals).toEqual(mockBackendGoals);
      expect(goals[0].title).toBe('Migrate to Real Backend Model');

      const tasks = await getTasks();
      expect(tasks).toEqual(mockBackendTasks);
      expect(tasks[0].title).toBe('Verify snapshot endpoint returns real data');
    });

    it('API failure does not silently display fabricated Orion demo data and returns empty state', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('Network error: 502 Bad Gateway'));

      const snapshot = await getPersonalSnapshot();

      expect(warnSpy).toHaveBeenCalled();
      expect(snapshot.projects).toEqual([]);
      expect(snapshot.goals).toEqual([]);
      expect(snapshot.tasks).toEqual([]);
      expect(snapshot.skills).toEqual([]);

      // Verify fabricated data is NOT returned
      expect(snapshot.projects.some((p) => p.name === 'Orion Personal AI')).toBe(false);
      expect(snapshot.goals.some((g) => g.title === 'Phase 5A UI Shell')).toBe(false);
      expect(snapshot.tasks.some((t) => t.title.includes('3-region'))).toBe(false);
    });
  });

  describe('UI Component Rendering', () => {
    it('1. Project from API appears in ProjectsPanel', () => {
      render(<ProjectsPanel projects={mockBackendProjects} />);
      expect(screen.getByText('Separation Proj')).toBeInTheDocument();
      expect(screen.getByText('Core separation project from SQLite')).toBeInTheDocument();
      expect(screen.getByText('ID #68')).toBeInTheDocument();
      expect(screen.getByText('/home/gfood/orion')).toBeInTheDocument();
      expect(screen.queryByText('Orion Personal AI')).not.toBeInTheDocument();
    });

    it('1b. Project from API appears in RightSidebar as Active Project', () => {
      render(
        <RightSidebar
          projects={mockBackendProjects}
          goals={[]}
          tasks={[]}
          skills={[]}
          activeProvider="nebius"
        />
      );
      expect(screen.getByText('Separation Proj')).toBeInTheDocument();
      expect(screen.queryByText('Orion Personal AI')).not.toBeInTheDocument();
    });

    it('2. Goals from API appear in GoalsPanel', () => {
      render(<GoalsPanel goals={mockBackendGoals} />);
      expect(screen.getByText('Migrate to Real Backend Model')).toBeInTheDocument();
      expect(screen.getByText('active')).toBeInTheDocument();
      expect(screen.getByText('1 Goals')).toBeInTheDocument();
      expect(screen.queryByText('Phase 5A UI Shell')).not.toBeInTheDocument();
    });

    it('2b. Goals from API appear in RightSidebar', () => {
      render(
        <RightSidebar
          projects={mockBackendProjects}
          goals={mockBackendGoals}
          tasks={[]}
          skills={[]}
          activeProvider="nebius"
        />
      );
      expect(screen.getByText('Current Goals (1)')).toBeInTheDocument();
      expect(screen.getByText('Migrate to Real Backend Model')).toBeInTheDocument();
      expect(screen.queryByText('Phase 5A UI Shell')).not.toBeInTheDocument();
    });

    it('3. Tasks from API appear in TasksPanel', () => {
      render(<TasksPanel tasks={mockBackendTasks} />);
      expect(screen.getByText('Verify snapshot endpoint returns real data')).toBeInTheDocument();
      expect(screen.getByText('high')).toBeInTheDocument();
      expect(screen.getByText('todo')).toBeInTheDocument();
      expect(screen.queryByText('Implement 3-region layout')).not.toBeInTheDocument();
    });

    it('3b. Tasks from API appear in RightSidebar', () => {
      render(
        <RightSidebar
          projects={mockBackendProjects}
          goals={[]}
          tasks={mockBackendTasks}
          skills={[]}
          activeProvider="nebius"
        />
      );
      expect(screen.getByText('Pending Tasks (1)')).toBeInTheDocument();
      expect(screen.getByText('Verify snapshot endpoint returns real data')).toBeInTheDocument();
      expect(screen.queryByText('Implement 3-region layout')).not.toBeInTheDocument();
    });

    it('4. Empty goals/tasks render correctly in GoalsPanel and TasksPanel', () => {
      render(<GoalsPanel goals={[]} />);
      expect(screen.getByText('0 Goals')).toBeInTheDocument();
      expect(screen.getByText('No goals registered in Personal Model.')).toBeInTheDocument();

      cleanup();

      render(<TasksPanel tasks={[]} />);
      expect(screen.getByText('0 Tasks')).toBeInTheDocument();
      expect(screen.getByText('No tasks registered in Personal Model.')).toBeInTheDocument();
    });

    it('4b. Empty goals/tasks/skills render correctly in RightSidebar', () => {
      render(
        <RightSidebar
          projects={mockBackendProjects}
          goals={[]}
          tasks={[]}
          skills={[]}
          activeProvider="nebius"
        />
      );
      expect(screen.getByText('Current Goals (0)')).toBeInTheDocument();
      expect(screen.getByText('No goals registered')).toBeInTheDocument();
      expect(screen.getByText('Pending Tasks (0)')).toBeInTheDocument();
      expect(screen.getByText('No tasks registered')).toBeInTheDocument();
      expect(screen.getByText('Stored Skills (0)')).toBeInTheDocument();
      expect(screen.getByText('No skills registered yet')).toBeInTheDocument();
    });

    it('5. API failure does not silently display fabricated Orion demo data in UI', () => {
      render(
        <RightSidebar
          projects={[]}
          goals={[]}
          tasks={[]}
          skills={[]}
          activeProvider="nebius"
        />
      );
      expect(screen.getByText('No active project assigned')).toBeInTheDocument();
      expect(screen.getByText('Current Goals (0)')).toBeInTheDocument();
      expect(screen.getByText('Pending Tasks (0)')).toBeInTheDocument();
      expect(screen.getByText('Stored Skills (0)')).toBeInTheDocument();

      expect(screen.queryByText('Orion Personal AI')).not.toBeInTheDocument();
      expect(screen.queryByText('Phase 5A UI Shell')).not.toBeInTheDocument();
      expect(screen.queryByText('Implement 3-region layout')).not.toBeInTheDocument();
      expect(screen.queryByText('Controlled Reusable Skills')).not.toBeInTheDocument();
    });

    it('renders SkillsPanel and expands workflow steps', () => {
      render(<SkillsPanel skills={mockSkills} />);
      expect(screen.getByText('Repo Status Review')).toBeInTheDocument();
      expect(screen.getByText('2 steps')).toBeInTheDocument();

      fireEvent.click(screen.getByText('Repo Status Review'));
      expect(screen.getByText('git_status')).toBeInTheDocument();
      expect(screen.getByText('read_file')).toBeInTheDocument();
    });

    it('renders MemoryPanel with category and importance', () => {
      render(<MemoryPanel memories={mockMemories} />);
      expect(screen.getByText('User prefers dark console interface.')).toBeInTheDocument();
      expect(screen.getByText('preference')).toBeInTheDocument();
    });
  });
});
