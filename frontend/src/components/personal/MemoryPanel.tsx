import React, { useState } from 'react';
import { EpisodicMemory } from '../../types/personal';
import { Badge } from '../common/Badge';
import { BrainCircuit, Star, Calendar, Trash2, Tag, Layers, RefreshCw } from 'lucide-react';

interface MemoryPanelProps {
  memories: EpisodicMemory[];
  onDeleteMemory?: (memoryId: number) => void;
  onRefresh?: () => Promise<void> | void;
  isLoading?: boolean;
  error?: string | null;
  className?: string;
}

export const MemoryPanel: React.FC<MemoryPanelProps> = ({
  memories,
  onDeleteMemory,
  onRefresh,
  isLoading = false,
  error = null,
  className = '',
}) => {
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const categories = ['all', ...Array.from(new Set(memories.map((m) => m.category || 'general')))];

  const filteredMemories = memories.filter((mem) => {
    const matchesCategory = filterCategory === 'all' || mem.category === filterCategory;
    const matchesSearch =
      !searchTerm ||
      mem.content.toLowerCase().includes(searchTerm.toLowerCase()) ||
      mem.category.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const handleDelete = async (id: number) => {
    if (!onDeleteMemory) return;
    setDeletingId(id);
    try {
      await onDeleteMemory(id);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className={`p-6 max-w-5xl mx-auto space-y-6 ${className}`} data-testid="memory-panel">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-slate-100 tracking-tight">Episodic Memory</h2>
          <p className="text-xs text-slate-400">
            Persistent conversational facts, user preferences, and project context learned across sessions.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={isLoading}
              title="Refresh memories"
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono bg-orion-900 border border-slate-800 text-slate-300 hover:text-cyan-400 hover:border-cyan-500/40 transition-colors disabled:opacity-50"
              data-testid="refresh-memory-button"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin text-cyan-400' : ''}`} />
              <span>{isLoading ? 'Refreshing...' : 'Refresh'}</span>
            </button>
          )}
          <Badge variant="cyan">{memories.length} Memories</Badge>
        </div>
      </div>

      {error && (
        <div
          className="p-3 rounded-lg border border-rose-800/80 bg-rose-950/40 text-rose-300 text-xs flex items-center justify-between"
          data-testid="memory-error"
        >
          <span>Error loading memories: {error}</span>
        </div>
      )}

      {/* Search and Category Filters */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-orion-900/60 p-3 rounded-xl border border-slate-800/80">
        <input
          type="text"
          placeholder="Filter memories by keyword..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="bg-orion-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500/50 w-full sm:w-64"
        />

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-mono text-slate-400 mr-1 flex items-center gap-1">
            <Tag className="w-3 h-3" /> Category:
          </span>
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setFilterCategory(cat)}
              className={`px-2 py-0.5 rounded text-[11px] font-mono transition-colors ${
                filterCategory === cat
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                  : 'bg-slate-800/60 text-slate-400 hover:text-slate-200 border border-transparent'
              }`}
            >
              {cat === 'all' ? 'All' : `#${cat}`}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {filteredMemories.map((mem) => (
          <div
            key={mem.id}
            className="rounded-xl border border-slate-800 bg-orion-900/80 p-4 space-y-2 hover:border-slate-750 transition-all group"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <BrainCircuit className="w-4 h-4 text-cyan-400 shrink-0" />
                <Badge variant="slate" size="sm">
                  {mem.category}
                </Badge>
                {mem.source_session && (
                  <span className="text-[10px] font-mono text-slate-500 flex items-center gap-1">
                    <Layers className="w-3 h-3 text-slate-600" />
                    Session: {mem.source_session.slice(0, 8)}...
                  </span>
                )}
              </div>

              <div className="flex items-center gap-3">
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

                {onDeleteMemory && (
                  <button
                    type="button"
                    onClick={() => handleDelete(mem.id)}
                    disabled={deletingId === mem.id}
                    title="Delete Memory"
                    className="text-slate-500 hover:text-rose-400 p-1 rounded transition-colors disabled:opacity-50"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>

            <p className="text-xs text-slate-200 leading-relaxed font-sans">
              {mem.content}
            </p>

            <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-500">
              <div className="flex items-center gap-1.5">
                <Calendar className="w-3 h-3 text-slate-600" />
                <span>
                  {mem.created_at ? `Learned ${new Date(mem.created_at).toLocaleString()}` : 'Recorded'}
                </span>
              </div>
              {mem.updated_at && mem.updated_at !== mem.created_at && (
                <span className="text-slate-500">
                  Updated: {new Date(mem.updated_at).toLocaleTimeString()}
                </span>
              )}
            </div>
          </div>
        ))}

        {filteredMemories.length === 0 && (
          <div className="p-12 text-center border border-dashed border-slate-800 rounded-xl text-slate-400 text-sm">
            {isLoading
              ? 'Loading episodic memories...'
              : memories.length === 0
              ? 'No memories recorded yet. Tell Orion facts or preferences in conversation to learn them.'
              : 'No memories match your filter criteria.'}
          </div>
        )}
      </div>
    </div>
  );
};
