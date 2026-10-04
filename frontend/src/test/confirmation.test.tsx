import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConfirmationCard } from '../components/conversation/ConfirmationCard';

describe('ConfirmationCard Component', () => {
  it('renders tool, summary, arguments and pending action buttons', () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);

    render(
      <ConfirmationCard
        confirmationId="cf-test-uuid-12345"
        tool="run_command"
        summary="Execute git diff to inspect working changes."
        argumentsData={{ command: 'git', arguments: ['diff'] }}
        onConfirm={onConfirm}
        status="pending"
      />
    );

    expect(screen.getByText('Action Requires Confirmation')).toBeInTheDocument();
    expect(screen.getByText('run_command')).toBeInTheDocument();
    expect(screen.getByText('Execute git diff to inspect working changes.')).toBeInTheDocument();
    expect(screen.getByText(/Bound Tool Arguments/i)).toBeInTheDocument();
    expect(screen.getByTestId('approve-button')).toBeInTheDocument();
    expect(screen.getByTestId('reject-button')).toBeInTheDocument();
  });

  it('triggers approve callback with exact server-generated confirmation ID', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);

    render(
      <ConfirmationCard
        confirmationId="cf-test-approve-888"
        tool="write_file"
        summary="Create file note.txt"
        argumentsData={{ path: 'note.txt', content: 'test' }}
        onConfirm={onConfirm}
        status="pending"
      />
    );

    const approveBtn = screen.getByTestId('approve-button');
    await fireEvent.click(approveBtn);

    expect(onConfirm).toHaveBeenCalledWith('cf-test-approve-888', true);
  });

  it('triggers reject callback with exact confirmation ID', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);

    render(
      <ConfirmationCard
        confirmationId="cf-test-reject-999"
        tool="delete_file"
        summary="Delete file old.txt"
        argumentsData={{ path: 'old.txt' }}
        onConfirm={onConfirm}
        status="pending"
      />
    );

    const rejectBtn = screen.getByTestId('reject-button');
    await fireEvent.click(rejectBtn);

    expect(onConfirm).toHaveBeenCalledWith('cf-test-reject-999', false);
  });

  it('renders executed and rejected feedback states correctly', () => {
    const onConfirm = vi.fn();

    const { rerender } = render(
      <ConfirmationCard
        confirmationId="cf-test-exec"
        tool="create_skill"
        summary="Create new skill"
        onConfirm={onConfirm}
        status="executed"
        result={{ status: 'created', skill_id: 42 }}
      />
    );

    expect(screen.getByText(/Action approved and executed successfully/i)).toBeInTheDocument();
    expect(screen.queryByTestId('approve-button')).not.toBeInTheDocument();

    rerender(
      <ConfirmationCard
        confirmationId="cf-test-exec"
        tool="create_skill"
        summary="Create new skill"
        onConfirm={onConfirm}
        status="rejected"
        feedbackMessage="User declined creation."
      />
    );

    expect(screen.getByText('User declined creation.')).toBeInTheDocument();
    expect(screen.queryByTestId('approve-button')).not.toBeInTheDocument();
  });

  it('renders create_skill arguments with Name, Description, and Workflow clearly', () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);

    render(
      <ConfirmationCard
        confirmationId="cf-skill-123"
        tool="create_skill"
        summary="Orion wants to create this skill:"
        argumentsData={{
          name: 'Git Status Check',
          description: 'Checks the current git status of the Orion workspace.',
          workflow: {
            steps: [
              {
                tool: 'git_status',
                arguments: {},
              },
            ],
          },
        }}
        onConfirm={onConfirm}
        status="pending"
      />
    );

    expect(screen.getByText('Name:')).toBeInTheDocument();
    expect(screen.getByText('Git Status Check')).toBeInTheDocument();
    expect(screen.getByText('Description:')).toBeInTheDocument();
    expect(screen.getByText('Checks the current git status of the Orion workspace.')).toBeInTheDocument();
    expect(screen.getByText('Workflow:')).toBeInTheDocument();
    expect(screen.getByText('git_status')).toBeInTheDocument();
  });
});
