import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MessageList, ExtendedMessage } from '../components/conversation/MessageList';
import { MessageInput } from '../components/conversation/MessageInput';

describe('Chat and Message Rendering', () => {
  it('renders welcome screen when message list is empty', () => {
    render(<MessageList messages={[]} />);
    expect(screen.getByText(/Orion Operating Layer Online/i)).toBeInTheDocument();
    expect(screen.getByText(/Chat Mode/i)).toBeInTheDocument();
    expect(screen.getByText(/Agent Mode/i)).toBeInTheDocument();
  });

  it('renders user and assistant messages with provider and context metadata', () => {
    const testMessages: ExtendedMessage[] = [
      {
        id: '1',
        role: 'user',
        content: 'What is my current project status?',
        timestamp: new Date().toISOString(),
      },
      {
        id: '2',
        role: 'assistant',
        content: 'Your active project is Orion Personal AI.',
        provider: 'nebius',
        model: 'nvidia/nemotron-70b',
        contextUsage: {
          memories_used: 3,
          memory_ids: [1, 2, 3],
          messages_used: 4,
        },
        timestamp: new Date().toISOString(),
      },
    ];

    render(<MessageList messages={testMessages} />);

    expect(screen.getByText('What is my current project status?')).toBeInTheDocument();
    expect(screen.getByText('Your active project is Orion Personal AI.')).toBeInTheDocument();
    expect(screen.getByText('nebius')).toBeInTheDocument();
    expect(screen.getByText('nvidia/nemotron-70b')).toBeInTheDocument();
    expect(screen.getByText(/3 memories/i)).toBeInTheDocument();
  });

  it('handles message input submission and mode toggling', () => {
    const handleSend = vi.fn().mockResolvedValue(undefined);
    const handleToggleMode = vi.fn();

    render(
      <MessageInput
        onSendMessage={handleSend}
        isLoading={false}
        mode="chat"
        onToggleMode={handleToggleMode}
      />
    );

    const input = screen.getByTestId('message-input');
    const sendButton = screen.getByTestId('send-button');

    // Type a message
    fireEvent.change(input, { target: { value: 'Hello Orion' } });
    expect(input).toHaveValue('Hello Orion');

    // Submit
    fireEvent.click(sendButton);
    expect(handleSend).toHaveBeenCalledWith('Hello Orion');

    // Toggle to agent mode
    const agentModeButton = screen.getByTestId('mode-agent');
    fireEvent.click(agentModeButton);
    expect(handleToggleMode).toHaveBeenCalledWith('agent');
  });
});
