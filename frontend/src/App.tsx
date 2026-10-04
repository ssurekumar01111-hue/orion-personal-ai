import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/layout/Header';
import { LeftSidebar, ActiveView } from './components/layout/LeftSidebar';
import { RightSidebar } from './components/layout/RightSidebar';
import { MessageList, ExtendedMessage } from './components/conversation/MessageList';
import { MessageInput } from './components/conversation/MessageInput';
import { ProjectsPanel } from './components/personal/ProjectsPanel';
import { GoalsPanel } from './components/personal/GoalsPanel';
import { TasksPanel } from './components/personal/TasksPanel';
import { SkillsPanel } from './components/personal/SkillsPanel';
import { MemoryPanel } from './components/personal/MemoryPanel';
import { SettingsPanel } from './components/personal/SettingsPanel';
import {
  sendChatMessage,
  runAgent,
  confirmAgentAction,
} from './api/chat';
import {
  createSession,
  listSessions,
  getSessionMessages,
  deleteSession,
} from './api/sessions';
import {
  getPersonalSnapshot,
  getSkills,
  getRecentMemories,
} from './api/personal';
import {
  getHealth,
  getProviders,
  getTools,
} from './api/system';
import { ProviderType, SessionItem } from './types/api';
import { Project, Goal, Task, Skill, EpisodicMemory } from './types/personal';

export const App: React.FC = () => {
  // Navigation & View state
  const [activeView, setActiveView] = useState<ActiveView>('conversation');
  const [mode, setMode] = useState<'chat' | 'agent'>('chat');
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(false);
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false);

  // System & Provider state
  const [provider, setProvider] = useState<ProviderType>('nebius');
  const [availableProviders, setAvailableProviders] = useState<ProviderType[]>(['nebius', 'hermes']);
  const [isOnline, setIsOnline] = useState<boolean>(true);
  const [registeredTools, setRegisteredTools] = useState<Array<{ name: string; description: string; permission: string }>>([]);

  // Session & Message state
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ExtendedMessage[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Personal Model Snapshot state
  const [projects, setProjects] = useState<Project[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [memories, setMemories] = useState<EpisodicMemory[]>([]);

  // Initial data loading
  const loadInitialData = useCallback(async () => {
    try {
      const [healthRes, provRes, toolsRes, sessionsRes, snapshot, mems] = await Promise.allSettled([
        getHealth(),
        getProviders(),
        getTools(),
        listSessions(20),
        getPersonalSnapshot(),
        getRecentMemories(20),
      ]);

      if (healthRes.status === 'fulfilled') {
        setIsOnline(true);
      } else {
        setIsOnline(false);
      }

      if (provRes.status === 'fulfilled') {
        setAvailableProviders(provRes.value.providers);
        if (provRes.value.default) {
          setProvider(provRes.value.default);
        }
      }

      if (toolsRes.status === 'fulfilled') {
        setRegisteredTools(toolsRes.value.tools);
      }

      if (sessionsRes.status === 'fulfilled') {
        setSessions(sessionsRes.value);
      }

      if (snapshot.status === 'fulfilled') {
        setProjects(snapshot.value.projects);
        setGoals(snapshot.value.goals);
        setTasks(snapshot.value.tasks);
        setSkills(snapshot.value.skills);
      }

      if (mems.status === 'fulfilled') {
        setMemories(mems.value);
      }
    } catch (err) {
      console.error('Error during initial system load:', err);
    }
  }, []);

  useEffect(() => {
    loadInitialData();
  }, [loadInitialData]);

  // Handle session selection and load history
  const handleSelectSession = async (sessionId: string) => {
    setActiveSessionId(sessionId);
    try {
      const history = await getSessionMessages(sessionId);
      const converted: ExtendedMessage[] = history.map((m, idx) => ({
        id: `hist-${m.id || idx}`,
        role: m.role,
        content: m.content,
        timestamp: m.created_at,
      }));
      setMessages(converted);
    } catch (err) {
      console.warn('Could not load session history:', err);
    }
  };

  // Handle creating a new session
  const handleNewSession = async () => {
    try {
      const newSess = await createSession('New Conversation');
      setSessions((prev) => [newSess, ...prev]);
      setActiveSessionId(newSess.id);
      setMessages([]);
      setActiveView('conversation');
    } catch {
      setActiveSessionId(null);
      setMessages([]);
      setActiveView('conversation');
    }
  };

  // Handle deleting a session
  const handleDeleteSession = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
  };

  // Handle sending a message
  const handleSendMessage = async (text: string) => {
    const userMsgId = `user-${Date.now()}`;
    const userMsg: ExtendedMessage = {
      id: userMsgId,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      if (mode === 'chat') {
        // Chat mode (POST /api/chat)
        const res = await sendChatMessage({
          message: text,
          provider,
          session_id: activeSessionId,
        });

        if (res.session_id && res.session_id !== activeSessionId) {
          setActiveSessionId(res.session_id);
          // Refresh session list to include newly created session
          listSessions(20).then(setSessions).catch(() => {});
        }

        const assistantMsg: ExtendedMessage = {
          id: `asst-${Date.now()}`,
          role: 'assistant',
          content: res.response,
          provider: res.provider,
          model: res.model,
          contextUsage: res.context,
          timestamp: new Date().toISOString(),
        };

        setMessages((prev) => [...prev, assistantMsg]);
      } else {
        // Agent mode (POST /api/agent/run)
        const res = await runAgent({
          message: text,
          provider,
          session_id: activeSessionId,
        });

        if (res.session_id && res.session_id !== activeSessionId) {
          setActiveSessionId(res.session_id);
          listSessions(20).then(setSessions).catch(() => {});
        }

        let confirmationData;
        if (res.confirmation_required && res.confirmation_id) {
          confirmationData = {
            confirmationId: res.confirmation_id,
            tool: res.tool_used || 'system_tool',
            summary: res.confirmation_summary || 'Mutating operation requires approval.',
            arguments: res.tool_arguments || null,
            status: 'pending' as const,
          };
        }

        const assistantMsg: ExtendedMessage = {
          id: `agent-${Date.now()}`,
          role: 'assistant',
          content: res.response,
          provider: res.provider,
          model: res.model,
          agentSteps: res.steps,
          confirmation: confirmationData,
          timestamp: new Date().toISOString(),
        };

        setMessages((prev) => [...prev, assistantMsg]);
      }
    } catch (err: unknown) {
      const errorText = err instanceof Error ? err.message : 'Unknown execution error occurred.';
      const errorMsg: ExtendedMessage = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: `Error: ${errorText}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle confirmation card approve or reject
  const handleConfirmAction = async (confirmationId: string, approved: boolean) => {
    try {
      const res = await confirmAgentAction({
        confirmation_id: confirmationId,
        approved,
      });

      // Update the confirmation state in messages
      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.confirmation && msg.confirmation.confirmationId === confirmationId) {
            return {
              ...msg,
              confirmation: {
                ...msg.confirmation,
                status: res.status === 'executed' ? 'executed' : 'rejected',
                result: res.result,
                feedbackMessage: res.message,
              },
            };
          }
          return msg;
        })
      );

      // Refresh Personal Model snapshots in case of mutation (skills, tasks, projects)
      const [snapshot, updatedSkills] = await Promise.all([
        getPersonalSnapshot(),
        getSkills(),
      ]);
      setProjects(snapshot.projects);
      setGoals(snapshot.goals);
      setTasks(snapshot.tasks);
      setSkills(updatedSkills);
    } catch (err: unknown) {
      const errorText = err instanceof Error ? err.message : 'Confirmation execution failed.';
      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.confirmation && msg.confirmation.confirmationId === confirmationId) {
            return {
              ...msg,
              confirmation: {
                ...msg.confirmation,
                status: 'error',
                feedbackMessage: errorText,
              },
            };
          }
          return msg;
        })
      );
    }
  };

  const activeSessionTitle =
    sessions.find((s) => s.id === activeSessionId)?.title ||
    (activeSessionId ? `Session ${activeSessionId.slice(0, 8)}` : 'New Session');

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-orion-950 text-slate-100 selection:bg-cyan-500/20 selection:text-cyan-300">
      {/* Left Sidebar Desktop & Mobile */}
      <div
        className={`fixed inset-y-0 left-0 z-30 transform lg:relative lg:translate-x-0 transition-transform duration-200 ease-in-out ${
          leftSidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <LeftSidebar
          activeView={activeView}
          onViewChange={(v) => {
            setActiveView(v);
            setLeftSidebarOpen(false);
          }}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={(id) => {
            handleSelectSession(id);
            setLeftSidebarOpen(false);
          }}
          onNewSession={handleNewSession}
          onDeleteSession={handleDeleteSession}
        />
      </div>

      {/* Backdrop overlay for mobile drawer */}
      {leftSidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setLeftSidebarOpen(false)}
        />
      )}

      {/* Center Main Region */}
      <div className="flex flex-col flex-1 min-w-0 h-full overflow-hidden">
        <Header
          provider={provider}
          onProviderChange={setProvider}
          availableProviders={availableProviders}
          isOnline={isOnline}
          activeSessionTitle={activeSessionTitle}
          onToggleLeftSidebar={() => setLeftSidebarOpen(!leftSidebarOpen)}
          onToggleRightSidebar={() => setRightSidebarOpen(!rightSidebarOpen)}
        />

        {/* View Switcher: Conversation vs Panels */}
        <main className="flex-1 overflow-hidden relative flex flex-col">
          {activeView === 'conversation' && (
            <>
              <div className="flex-1 overflow-y-auto">
                <MessageList
                  messages={messages}
                  isLoading={isLoading}
                  onConfirmAction={handleConfirmAction}
                />
              </div>

              <MessageInput
                onSendMessage={handleSendMessage}
                isLoading={isLoading}
                mode={mode}
                onToggleMode={setMode}
              />
            </>
          )}

          {activeView === 'projects' && (
            <div className="flex-1 overflow-y-auto">
              <ProjectsPanel projects={projects} />
            </div>
          )}

          {activeView === 'goals' && (
            <div className="flex-1 overflow-y-auto">
              <GoalsPanel goals={goals} />
            </div>
          )}

          {activeView === 'tasks' && (
            <div className="flex-1 overflow-y-auto">
              <TasksPanel tasks={tasks} />
            </div>
          )}

          {activeView === 'skills' && (
            <div className="flex-1 overflow-y-auto">
              <SkillsPanel skills={skills} />
            </div>
          )}

          {activeView === 'memory' && (
            <div className="flex-1 overflow-y-auto">
              <MemoryPanel memories={memories} />
            </div>
          )}

          {activeView === 'settings' && (
            <div className="flex-1 overflow-y-auto">
              <SettingsPanel tools={registeredTools} isOnline={isOnline} />
            </div>
          )}
        </main>
      </div>

      {/* Right Sidebar Desktop & Mobile */}
      <div
        className={`fixed inset-y-0 right-0 z-30 transform xl:relative xl:translate-x-0 transition-transform duration-200 ease-in-out ${
          rightSidebarOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <RightSidebar
          projects={projects}
          goals={goals}
          tasks={tasks}
          skills={skills}
          activeProvider={provider}
          activeModel={provider === 'hermes' ? 'Hermes 405B' : 'Nemotron 70B'}
        />
      </div>

      {/* Backdrop overlay for right drawer on small screens */}
      {rightSidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm xl:hidden"
          onClick={() => setRightSidebarOpen(false)}
        />
      )}
    </div>
  );
};

export default App;
