import React from 'react';
import { AgentStep } from '../../types/agent';
import { Badge } from '../common/Badge';
import { ActivityTimeline } from '../agent/ActivityTimeline';
import { ConfirmationCard } from './ConfirmationCard';
import {
  Bot,
  User,
  Database,
} from 'lucide-react';

export interface ExtendedMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  provider?: string;
  model?: string;
  contextUsage?: {
    memories_used?: number;
    memory_ids?: number[];
    messages_used?: number;
  };
  agentSteps?: AgentStep[];
  confirmation?: {
    confirmationId: string;
    tool: string;
    summary?: string | null;
    arguments?: Record<string, unknown> | null;
    status: 'pending' | 'executed' | 'rejected' | 'error';
    result?: unknown;
    feedbackMessage?: string | null;
  };
}

interface MessageListProps {
  messages: ExtendedMessage[];
  isLoading?: boolean;
  onConfirmAction?: (confirmationId: string, approved: boolean) => Promise<void>;
  className?: string;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isLoading = false,
  onConfirmAction,
  className = '',
}) => {
  if (messages.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center h-full p-8 text-center ${className}`}>
        <div className="w-14 h-14 rounded-2xl bg-orion-900 border border-slate-800 flex items-center justify-center mb-4 text-cyan-400 shadow-xl shadow-cyan-950/10">
          <Bot className="w-7 h-7" />
        </div>
        <h2 className="text-lg font-semibold text-slate-200 tracking-tight mb-1">
          Orion Operating Layer Online
        </h2>
        <p className="text-xs text-slate-400 max-w-md leading-relaxed">
          Private, bounded personal AI with structured memory, workspace tools, and user-confirmed mutations.
        </p>

        <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-w-lg w-full text-left text-xs">
          <div className="p-3 rounded-lg border border-slate-800/80 bg-orion-900/60 text-slate-300">
            <span className="font-mono text-cyan-400 block text-[11px] mb-1">→ Chat Mode</span>
            Direct LLM reasoning with episodic memory recall and session history.
          </div>
          <div className="p-3 rounded-lg border border-slate-800/80 bg-orion-900/60 text-slate-300">
            <span className="font-mono text-emerald-400 block text-[11px] mb-1">→ Agent Mode</span>
            Bounded 5-iteration planner with workspace tools and confirmation boundaries.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`space-y-6 p-4 sm:p-6 overflow-y-auto ${className}`} data-testid="message-list">
      {messages.map((msg) => {
        const isUser = msg.role === 'user';

        return (
          <div
            key={msg.id}
            className={`flex gap-3 sm:gap-4 max-w-4xl mx-auto ${
              isUser ? 'justify-end' : 'justify-start'
            }`}
            data-testid={`message-${msg.role}`}
          >
            {!isUser && (
              <div className="w-8 h-8 rounded-lg bg-orion-850 border border-slate-800 flex items-center justify-center shrink-0 text-cyan-400 mt-1">
                <Bot className="w-4 h-4" />
              </div>
            )}

            <div className={`flex flex-col space-y-2.5 ${isUser ? 'items-end max-w-2xl' : 'items-start flex-1'}`}>
              {/* Message Header (Provider, Model, Context) */}
              {!isUser && (msg.provider || msg.model || msg.contextUsage) && (
                <div className="flex items-center gap-2 flex-wrap text-[11px] font-mono text-slate-400">
                  {msg.provider && (
                    <Badge variant={msg.provider === 'hermes' ? 'purple' : 'cyan'}>
                      {msg.provider}
                    </Badge>
                  )}

                  {msg.model && (
                    <span className="text-slate-400 truncate max-w-xs" title={msg.model}>
                      {msg.model}
                    </span>
                  )}

                  {msg.contextUsage && (
                    <div className="flex items-center gap-1.5 text-slate-400 pl-1 border-l border-slate-800">
                      <Database className="w-3 h-3 text-cyan-500" />
                      <span>{msg.contextUsage.memories_used || 0} memories</span>
                    </div>
                  )}
                </div>
              )}

              {/* Agent execution steps timeline */}
              {!isUser && msg.agentSteps && msg.agentSteps.length > 0 && (
                <div className="w-full">
                  <ActivityTimeline steps={msg.agentSteps} />
                </div>
              )}

              {/* Confirmation Card if required */}
              {!isUser && msg.confirmation && onConfirmAction && (
                <div className="w-full">
                  <ConfirmationCard
                    confirmationId={msg.confirmation.confirmationId}
                    tool={msg.confirmation.tool}
                    summary={msg.confirmation.summary}
                    argumentsData={msg.confirmation.arguments}
                    status={msg.confirmation.status}
                    result={msg.confirmation.result}
                    feedbackMessage={msg.confirmation.feedbackMessage}
                    onConfirm={onConfirmAction}
                  />
                </div>
              )}

              {/* Message Bubble */}
              {msg.content && (
                <div
                  className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    isUser
                      ? 'bg-cyan-600/90 text-white shadow-md'
                      : 'bg-orion-900 border border-slate-800 text-slate-200 shadow-sm w-full'
                  }`}
                >
                  <p className="whitespace-pre-wrap font-sans">{msg.content}</p>
                </div>
              )}

              {/* Timestamp */}
              {msg.timestamp && (
                <span className="text-[10px] font-mono text-slate-400 px-1">
                  {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </div>

            {isUser && (
              <div className="w-8 h-8 rounded-lg bg-cyan-950 border border-cyan-800/80 flex items-center justify-center shrink-0 text-cyan-300 mt-1">
                <User className="w-4 h-4" />
              </div>
            )}
          </div>
        );
      })}

      {isLoading && (
        <div className="flex gap-3 max-w-4xl mx-auto items-start">
          <div className="w-8 h-8 rounded-lg bg-orion-850 border border-slate-800 flex items-center justify-center shrink-0 text-cyan-400 mt-1">
            <Bot className="w-4 h-4 animate-pulse" />
          </div>
          <div className="rounded-2xl px-4 py-3 bg-orion-900 border border-slate-800 text-slate-400 text-xs flex items-center gap-2">
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
            <span className="font-mono text-[11px] text-slate-400">Orion is planning and synthesizing...</span>
          </div>
        </div>
      )}
    </div>
  );
};
