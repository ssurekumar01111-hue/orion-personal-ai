import React from 'react';
import { EpisodicMemory } from '../../types/personal';
import { Badge } from '../common/Badge';
import { BrainCircuit, Star, Calendar } from 'lucide-react';

interface MemoryPanelProps {
  memories: EpisodicMemory[];
  className?: string;
}

export const MemoryPanel: React.FC<MemoryPanelProps> = ({
  memories,
  className = '',
}) => {
  return (
    <div className={`p-6 max-w-5xl mx-auto space-y-6 ${className}`} data-testid="memory-panel">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-slate-100 tracking-tight">Episodic Memory</h2>
          <p className="text-xs text-slate-400">
            Episodic memories retrieved by semantic and keyword recall during reasoning.
          </p>
        </div>
        <Badge variant="cyan">{memories.length} Memories</Badge>
      </div>

      <div className="space-y-3">
        {memories.map((mem) => (
          <div
            key={mem.id}
            className="rounded-xl border border-slate-800 bg-orion-900/80 p-4 space-y-2 hover:border-slate-750 transition-all"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <BrainCircuit className="w-4 h-4 text-cyan-400 shrink-0" />
                <Badge variant="slate" size="sm">
                  {mem.category}
                </Badge>
              </div>

              <div className="flex items-center gap-1 text-amber-400 text-xs font-mono" title={`Importance ${mem.importance}/5`}>
                {Array.from({ length: 5 }).map((_, i) => (
                  <Star
                    key={i}
                    className={`w-3 h-3 ${
                      i < mem.importance ? 'fill-amber-400 text-amber-400' : 'text-slate-700'
                    }`}
                  />
                ))}
              </div>
            </div>

            <p className="text-xs text-slate-200 leading-relaxed font-sans">
              {mem.content}
            </p>

            {mem.created_at && (
              <div className="pt-2 border-t border-slate-800/80 flex items-center gap-1.5 text-[10px] font-mono text-slate-500">
                <Calendar className="w-3 h-3 text-slate-600" />
                <span>Recorded {new Date(mem.created_at).toLocaleString()}</span>
              </div>
            )}
          </div>
        ))}

        {memories.length === 0 && (
          <div className="p-12 text-center border border-dashed border-slate-800 rounded-xl text-slate-400 text-sm">
            No memories recorded yet in episodic memory store.
          </div>
        )}
      </div>
    </div>
  );
};
