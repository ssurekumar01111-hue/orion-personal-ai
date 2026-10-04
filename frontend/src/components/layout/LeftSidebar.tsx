import React from 'react';
import { SessionItem } from '../../types/api';
import {
  FolderKanban,
  Target,
  CheckSquare,
  Wrench,
  BrainCircuit,
  MessageSquare,
  Plus,
  Trash2,
  Sliders,
  Sparkles,
} from 'lucide-react';

export type ActiveView = 'conversation' | 'projects' | 'goals' | 'tasks' | 'skills' | 'memory' | 'settings';

interface LeftSidebarProps {
  activeView: ActiveView;
  onViewChange: (view: ActiveView) => void;
  sessions: SessionItem[];
  activeSessionId?: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession?: (id: string) => void;
  className?: string;
}

export const LeftSidebar: React.FC<LeftSidebarProps> = ({
  activeView,
  onViewChange,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  className = '',
}) => {
  const navItems = [
    { id: 'conversation', label: 'Console / Chat', icon: MessageSquare },
    { id: 'projects', label: 'Projects', icon: FolderKanban },
    { id: 'goals', label: 'Goals', icon: Target },
    { id: 'tasks', label: 'Tasks', icon: CheckSquare },
    { id: 'skills', label: 'Skills', icon: Wrench },
    { id: 'memory', label: 'Episodic Memory', icon: BrainCircuit },
  ] as const;

  return (
    <aside
      className={`w-64 border-r border-slate-800 bg-orion-950 flex flex-col h-full shrink-0 select-none ${className}`}
      data-testid="left-sidebar"
    >
      {/* Orion Brand Header */}
      <div className="p-4 border-b border-slate-800/80 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-cyan-950 border border-cyan-700/60 flex items-center justify-center text-cyan-400 shadow-sm shadow-cyan-950/40">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-mono text-sm font-bold tracking-wider text-slate-100 uppercase">
              ORION
            </h1>
            <span className="text-[10px] text-cyan-400 font-mono tracking-tight block">
              AI OPERATING LAYER
            </span>
          </div>
        </div>
      </div>

      {/* Main Navigation */}
      <div className="p-3 space-y-1">
        <span className="text-[10px] font-mono uppercase text-slate-400 px-3 block mb-1.5 font-semibold">
          Navigation
        </span>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeView === item.id;

          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onViewChange(item.id as ActiveView)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${
                isActive
                  ? 'bg-orion-850 text-cyan-300 border border-slate-800 shadow-sm font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-orion-900/60 border border-transparent'
              }`}
              data-testid={`nav-${item.id}`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-cyan-400' : 'text-slate-500'}`} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Sessions Section */}
      <div className="flex-1 p-3 overflow-y-auto space-y-2 border-t border-slate-800/80">
        <div className="flex items-center justify-between px-3">
          <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold">
            Conversations
          </span>
          <button
            type="button"
            onClick={onNewSession}
            className="p-1 rounded text-cyan-400 hover:text-cyan-300 hover:bg-slate-800/80 transition-colors"
            title="Start New Session"
            data-testid="new-session-button"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="space-y-1">
          {sessions.map((s) => {
            const isSelected = s.id === activeSessionId && activeView === 'conversation';

            return (
              <div
                key={s.id}
                className={`group flex items-center justify-between rounded-lg px-3 py-2 text-xs transition-colors cursor-pointer border ${
                  isSelected
                    ? 'bg-cyan-950/40 text-cyan-300 border-cyan-800/50'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/50 border-transparent'
                }`}
                onClick={() => {
                  onSelectSession(s.id);
                  onViewChange('conversation');
                }}
              >
                <div className="truncate flex-1 pr-2">
                  <span className="truncate block font-medium">
                    {s.title || 'Untitled Session'}
                  </span>
                  <span className="text-[10px] font-mono text-slate-400 block truncate">
                    {new Date(s.created_at).toLocaleDateString([], {
                      month: 'short',
                      day: 'numeric',
                    })}
                  </span>
                </div>

                {onDeleteSession && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(s.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400 p-1 transition-opacity"
                    title="Delete session"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            );
          })}

          {sessions.length === 0 && (
            <div className="text-[11px] text-slate-400 px-3 py-2 italic font-mono">
              No previous sessions
            </div>
          )}
        </div>
      </div>

      {/* Footer / Settings Status */}
      <div className="p-3 border-t border-slate-800/80 bg-orion-900/40 text-xs">
        <button
          type="button"
          onClick={() => onViewChange('settings')}
          className={`w-full flex items-center justify-between p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 transition-colors ${
            activeView === 'settings' ? 'text-cyan-300 bg-slate-800/60' : ''
          }`}
          data-testid="nav-settings"
        >
          <div className="flex items-center gap-2">
            <Sliders className="w-4 h-4 text-slate-400" />
            <span className="text-xs">Security & System</span>
          </div>
          <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800/60 px-1.5 py-0.5 rounded">
            LOCKED
          </span>
        </button>
      </div>
    </aside>
  );
};
