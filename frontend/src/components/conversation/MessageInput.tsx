import React, { useState, useRef, useEffect } from 'react';
import { Button } from '../common/Button';
import { Bot, Send, MessageSquare } from 'lucide-react';

interface MessageInputProps {
  onSendMessage: (message: string) => Promise<void>;
  isLoading: boolean;
  mode: 'chat' | 'agent';
  onToggleMode: (mode: 'chat' | 'agent') => void;
  disabled?: boolean;
  className?: string;
}

export const MessageInput: React.FC<MessageInputProps> = ({
  onSendMessage,
  isLoading,
  mode,
  onToggleMode,
  disabled = false,
  className = '',
}) => {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`;
    }
  }, [text]);

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!text.trim() || isLoading || disabled) return;

    const messageToSend = text.trim();
    setText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    await onSendMessage(messageToSend);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className={`border-t border-slate-800/90 bg-orion-950/90 p-4 backdrop-blur-md ${className}`}>
      <div className="max-w-4xl mx-auto space-y-2.5">
        {/* Mode & Prompt Controls */}
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-1.5 p-0.5 bg-orion-900 rounded-lg border border-slate-800">
            <button
              type="button"
              onClick={() => onToggleMode('chat')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-all ${
                mode === 'chat'
                  ? 'bg-slate-800 text-cyan-300 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              data-testid="mode-chat"
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Chat Mode</span>
            </button>

            <button
              type="button"
              onClick={() => onToggleMode('agent')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium transition-all ${
                mode === 'agent'
                  ? 'bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              data-testid="mode-agent"
            >
              <Bot className="w-3.5 h-3.5" />
              <span>Agent Mode</span>
              <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-cyan-900/40 text-cyan-400">
                5x loop
              </span>
            </button>
          </div>

          <div className="text-[11px] font-mono text-slate-500 hidden sm:block">
            {mode === 'agent' ? 'Multi-step autonomous planner active' : 'Direct synthesis with memory recall'}
          </div>
        </div>

        {/* Text Input Box */}
        <form onSubmit={handleSubmit} className="relative flex items-end gap-2">
          <div className="relative flex-1">
            <textarea
              ref={textareaRef}
              rows={1}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled || isLoading}
              placeholder={
                mode === 'agent'
                  ? "Instruct Orion agent (e.g., 'Inspect repo files and summarize tasks')..."
                  : "Message Orion (e.g., 'What are my active goals?')..."
              }
              className="w-full resize-none rounded-xl bg-orion-900 border border-slate-800 px-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-cyan-500/80 focus:outline-none focus:ring-1 focus:ring-cyan-500/40 disabled:opacity-50 min-h-[44px] max-h-[180px] leading-relaxed transition-all"
              data-testid="message-input"
            />
          </div>

          <Button
            type="submit"
            variant="primary"
            size="md"
            disabled={!text.trim() || isLoading || disabled}
            isLoading={isLoading}
            data-testid="send-button"
            className="h-[44px] px-4 shrink-0"
            aria-label="Send message"
          >
            <Send className="w-4 h-4" />
          </Button>
        </form>

        <div className="flex items-center justify-between text-[11px] text-slate-500 px-1 font-mono">
          <span>Press Enter to send, Shift+Enter for new line</span>
          <span>Orion Guardrails Active</span>
        </div>
      </div>
    </div>
  );
};
