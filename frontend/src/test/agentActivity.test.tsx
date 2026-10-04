import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ActivityTimeline } from '../components/agent/ActivityTimeline';
import { AgentStep } from '../types/agent';

describe('ActivityTimeline Component', () => {
  it('renders multi-step agent execution sequence', () => {
    const steps: AgentStep[] = [
      {
        step: 1,
        action: 'tool',
        tool: 'git_status',
        arguments: {},
        permission: 'automatic',
        status: 'executed',
        result: { clean: true, branch: 'master' },
      },
      {
        step: 2,
        action: 'tool',
        tool: 'read_file',
        arguments: { path: 'README.md' },
        permission: 'automatic',
        status: 'executed',
        result: 'Project Overview',
      },
      {
        step: 3,
        action: 'respond',
        status: 'completed',
      },
    ];

    render(<ActivityTimeline steps={steps} />);

    expect(screen.getByText(/Agent Activity Timeline/i)).toBeInTheDocument();
    expect(screen.getByText(/Bounded loop: 3\/5 steps/i)).toBeInTheDocument();
    expect(screen.getByText(/TOOL → git_status/i)).toBeInTheDocument();
    expect(screen.getByText(/TOOL → read_file/i)).toBeInTheDocument();
    expect(screen.getByText(/respond/i)).toBeInTheDocument();
  });

  it('renders confirmation_required and expands step details', () => {
    const steps: AgentStep[] = [
      {
        step: 1,
        action: 'tool',
        tool: 'write_file',
        arguments: { path: 'data/notes.txt', content: 'Secret thoughts' },
        permission: 'confirmation_required',
        status: 'confirmation_required',
        confirmation_id: 'cf-991823ab1234',
      },
    ];

    render(<ActivityTimeline steps={steps} />);

    expect(screen.getByText(/TOOL → write_file/i)).toBeInTheDocument();
    expect(screen.getByText('confirmation required')).toBeInTheDocument();
    expect(screen.getByText(/ID: cf-991823a.../i)).toBeInTheDocument();

    // Click to expand arguments
    const stepRow = screen.getByText(/TOOL → write_file/i);
    fireEvent.click(stepRow);

    expect(screen.getByText(/Arguments/i)).toBeInTheDocument();
    expect(screen.getByText(/data\/notes.txt/i)).toBeInTheDocument();
  });
});
