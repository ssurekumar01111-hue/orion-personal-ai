import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Header } from '../components/layout/Header';

describe('Header & Provider Selector Component', () => {
  it('renders active provider and switches between available providers', () => {
    const handleProviderChange = vi.fn();

    render(
      <Header
        provider="nebius"
        onProviderChange={handleProviderChange}
        availableProviders={['nebius', 'hermes']}
        isOnline={true}
        activeSessionTitle="Active Agent Run"
        onToggleLeftSidebar={vi.fn()}
        onToggleRightSidebar={vi.fn()}
      />
    );

    expect(screen.getByText('Active Agent Run')).toBeInTheDocument();
    expect(screen.getByText('ONLINE')).toBeInTheDocument();

    const select = screen.getByTestId('provider-select');
    expect(select).toHaveValue('nebius');

    fireEvent.change(select, { target: { value: 'hermes' } });
    expect(handleProviderChange).toHaveBeenCalledWith('hermes');
  });

  it('renders offline status when system is disconnected', () => {
    render(
      <Header
        provider="hermes"
        onProviderChange={vi.fn()}
        availableProviders={['nebius', 'hermes']}
        isOnline={false}
        activeSessionTitle="Offline Session"
        onToggleLeftSidebar={vi.fn()}
        onToggleRightSidebar={vi.fn()}
      />
    );

    expect(screen.getByText('OFFLINE')).toBeInTheDocument();
  });
});
