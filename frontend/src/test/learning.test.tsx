import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ActivityTimeline } from '../components/agent/ActivityTimeline';
import { MemoryPanel } from '../components/personal/MemoryPanel';
import { SkillsPanel } from '../components/personal/SkillsPanel';
import { AgentStep } from '../types/agent';
import { EpisodicMemory, Skill } from '../types/personal';

describe('LEARN Stage Frontend Integration', () => {
  it('ActivityTimeline renders learn stage step and learned badge', () => {
    const steps: AgentStep[] = [
      {
        step: 1,
        action: 'tool',
        tool: 'git_status',
        status: 'executed',
        permission: 'automatic',
      },
      {
        step: 2,
        action: 'learn',
        status: 'learned',
      },
    ];

    render(<ActivityTimeline steps={steps} />);
    expect(screen.getByText('learn')).toBeInTheDocument();
    expect(screen.getByText('learned')).toBeInTheDocument();
  });

  it('MemoryPanel displays memory items and triggers onDeleteMemory callback', () => {
    const mockMemories: EpisodicMemory[] = [
      {
        id: 42,
        content: 'Internal codename is BLUE ORBIT 47',
        category: 'project',
        importance: 5,
        source_session: 'session-orbit',
        created_at: new Date().toISOString(),
      },
    ];

    const handleDelete = vi.fn();
    render(<MemoryPanel memories={mockMemories} onDeleteMemory={handleDelete} />);

    expect(screen.getByText('Internal codename is BLUE ORBIT 47')).toBeInTheDocument();
    expect(screen.getByText('project')).toBeInTheDocument();

    const deleteBtn = screen.getByTitle('Delete Memory');
    expect(deleteBtn).toBeInTheDocument();
    fireEvent.click(deleteBtn);
    expect(handleDelete).toHaveBeenCalledWith(42);
  });

  it('SkillsPanel renders registered skills and expansion toggles', () => {
    const mockSkills: Skill[] = [
      {
        id: 7,
        name: 'Automated Build Check',
        description: 'Verify build steps and git status',
        workflow: {
          steps: [
            { tool: 'git_status', arguments: {} },
          ],
        },
      },
    ];

    render(<SkillsPanel skills={mockSkills} />);
    expect(screen.getByText('Automated Build Check')).toBeInTheDocument();
    expect(screen.getByText('1 steps')).toBeInTheDocument();
  });
});
