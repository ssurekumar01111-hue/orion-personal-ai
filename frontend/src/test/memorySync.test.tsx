import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react';
import { App } from '../App';
import { setDemoKey } from '../api/client';
import { EpisodicMemory } from '../types/personal';

describe('Frontend Memory State Synchronization (Fix A)', () => {
  const initialMemories: EpisodicMemory[] = [
    {
      id: 1,
      content: 'Workspace operations are strictly confined to workspace directory.',
      category: 'security',
      importance: 5,
      created_at: '2026-10-30T00:00:00Z',
    },
  ];

  const newMemory: EpisodicMemory = {
    id: 2,
    content: 'My project codename is BLUE ORBIT 47. It is a personal AI research project',
    category: 'project',
    importance: 5,
    created_at: '2026-10-30T01:00:00Z',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    setDemoKey('test-demo-key-1234567890123456789012');
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('refreshes memory state in Chat Mode when extracted_memories is returned', async () => {
    let recentMemoriesCalled = 0;

    const mockFetch = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      const urlStr = String(url);

      if (urlStr.includes('/health')) {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/providers')) {
        return new Response(JSON.stringify({ providers: ['nebius'], default: 'nebius' }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/tools')) {
        return new Response(JSON.stringify({ tools: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/sessions') && init?.method !== 'POST') {
        return new Response(JSON.stringify({ sessions: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/personal/snapshot')) {
        return new Response(JSON.stringify({ projects: [], goals: [], tasks: [], skills: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/memory/recent')) {
        recentMemoriesCalled++;
        const currentList = recentMemoriesCalled > 1 ? [newMemory, ...initialMemories] : initialMemories;
        return new Response(JSON.stringify({ memories: currentList }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/chat')) {
        return new Response(
          JSON.stringify({
            session_id: 'sess-new',
            provider: 'nebius',
            model: 'nemotron-70b',
            response: 'I have saved this to persistent episodic memory for future conversations.',
            extracted_memories: [newMemory],
            context: { memories_used: 1, memory_ids: [1], messages_used: 1 },
          }),
          { status: 200, headers: { 'content-type': 'application/json' } }
        );
      }

      return new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } });
    });

    global.fetch = mockFetch;

    render(<App />);

    // Wait for initial load
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith('/api/memory/recent?limit=20', expect.anything());
    });

    // Send chat message in Chat mode
    const input = screen.getByTestId('message-input');
    const sendBtn = screen.getByTestId('send-button');

    await act(async () => {
      fireEvent.change(input, {
        target: {
          value: 'Remember this for future conversations: My project codename is BLUE ORBIT 47. It is a personal AI research project.',
        },
      });
      fireEvent.click(sendBtn);
    });

    // Verify /api/chat was called and /api/memory/recent was refreshed
    await waitFor(() => {
      expect(screen.getByText(/I have saved this to persistent episodic memory/i)).toBeInTheDocument();
      expect(recentMemoriesCalled).toBeGreaterThanOrEqual(2);
    });

    // Navigate to Episodic Memory view
    const memoryNav = screen.getByTestId('nav-memory');
    await act(async () => {
      fireEvent.click(memoryNav);
    });

    // Verify new memory is displayed in Episodic Memory panel
    await waitFor(() => {
      expect(screen.getByText(/BLUE ORBIT 47/i)).toBeInTheDocument();
      expect(screen.getByText(/Workspace operations/i)).toBeInTheDocument();
    });
  });

  it('merges memory updates without inserting duplicate records', async () => {
    let recentMemoriesCount = 0;

    const mockFetch = vi.fn().mockImplementation(async (url: string) => {
      const urlStr = String(url);

      if (urlStr.includes('/api/memory/recent')) {
        recentMemoriesCount++;
        // Return same memory on repeated calls
        return new Response(JSON.stringify({ memories: [newMemory] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/health')) {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/providers')) {
        return new Response(JSON.stringify({ providers: ['nebius'] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/tools')) {
        return new Response(JSON.stringify({ tools: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/sessions')) {
        return new Response(JSON.stringify({ sessions: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/personal/snapshot')) {
        return new Response(JSON.stringify({ projects: [], goals: [], tasks: [], skills: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }

      return new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } });
    });

    global.fetch = mockFetch;

    render(<App />);

    // Navigate to memory view
    const memoryNav = screen.getByTestId('nav-memory');
    await act(async () => {
      fireEvent.click(memoryNav);
    });

    await waitFor(() => {
      expect(screen.getByText(/BLUE ORBIT 47/i)).toBeInTheDocument();
    });

    // Click refresh button in MemoryPanel
    const refreshBtn = screen.getByTestId('refresh-memory-button');
    await act(async () => {
      fireEvent.click(refreshBtn);
    });

    await waitFor(() => {
      // Memory badge must state "1 Memories", not 2 duplicates
      expect(screen.getByText('1 Memories')).toBeInTheDocument();
    });
  });

  it('preserves existing memories and displays error when refresh fails', async () => {
    let shouldFail = false;

    const mockFetch = vi.fn().mockImplementation(async (url: string) => {
      const urlStr = String(url);

      if (urlStr.includes('/api/memory/recent')) {
        if (shouldFail) {
          return new Response(JSON.stringify({ detail: 'Database connection failed' }), {
            status: 500,
            headers: { 'content-type': 'application/json' },
          });
        }
        return new Response(JSON.stringify({ memories: initialMemories }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      if (urlStr.includes('/health')) {
        return new Response(JSON.stringify({ status: 'ok' }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/providers')) {
        return new Response(JSON.stringify({ providers: ['nebius'] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/tools')) {
        return new Response(JSON.stringify({ tools: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/sessions')) {
        return new Response(JSON.stringify({ sessions: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      if (urlStr.includes('/api/personal/snapshot')) {
        return new Response(JSON.stringify({ projects: [], goals: [], tasks: [], skills: [] }), { status: 200, headers: { 'content-type': 'application/json' } });
      }

      return new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } });
    });

    global.fetch = mockFetch;

    render(<App />);

    // Navigate to memory view
    const memoryNav = screen.getByTestId('nav-memory');
    await act(async () => {
      fireEvent.click(memoryNav);
    });

    await waitFor(() => {
      expect(screen.getByText(/Workspace operations/i)).toBeInTheDocument();
    });

    // Make future refreshes fail
    shouldFail = true;

    const refreshBtn = screen.getByTestId('refresh-memory-button');
    await act(async () => {
      fireEvent.click(refreshBtn);
    });

    // Error banner is shown and existing memory is preserved
    await waitFor(() => {
      expect(screen.getByTestId('memory-error')).toBeInTheDocument();
      expect(screen.getByText(/Database connection failed/i)).toBeInTheDocument();
      expect(screen.getByText(/Workspace operations/i)).toBeInTheDocument();
    });
  });
});
