import React from 'react';
import { Goal } from '../../types/personal';
import { Badge } from '../common/Badge';
import { Target } from 'lucide-react';

interface GoalsPanelProps {
  goals: Goal[];
  className?: string;
}

export const GoalsPanel: React.FC<GoalsPanelProps> = ({
  goals,
  className = '',
}) => {
  return (
    <div className={`p-6 max-w-5xl mx-auto space-y-6 ${className}`} data-testid="goals-panel">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-slate-100 tracking-tight">Goals</h2>
          <p className="text-xs text-slate-400">
            Objectives and outcomes tracked in Orion's Personal Model.
          </p>
        </div>
        <Badge variant="cyan">{goals.length} Goals</Badge>
      </div>

      <div className="space-y-3">
        {goals.map((goal) => {
          const isCompleted = goal.status === 'completed';

          return (
            <div
              key={goal.id}
              className="rounded-xl border border-slate-800 bg-orion-900/80 p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 hover:border-slate-750 transition-all"
            >
              <div className="flex items-start gap-3">
                <div
                  className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${
                    isCompleted
                      ? 'bg-emerald-950/60 border border-emerald-800 text-emerald-400'
                      : 'bg-cyan-950/60 border border-cyan-800 text-cyan-400'
                  }`}
                >
                  <Target className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-medium text-slate-200 text-sm">{goal.title}</h3>
                  <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
                    {goal.description || 'No description provided.'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3 self-end sm:self-center shrink-0">
                {goal.project_id && (
                  <span className="text-[11px] font-mono text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-750">
                    Project #{goal.project_id}
                  </span>
                )}
                <Badge
                  variant={
                    isCompleted
                      ? 'emerald'
                      : goal.status === 'in_progress' || goal.status === 'active'
                      ? 'cyan'
                      : 'slate'
                  }
                >
                  {goal.status}
                </Badge>
              </div>
            </div>
          );
        })}

        {goals.length === 0 && (
          <div className="p-12 text-center border border-dashed border-slate-800 rounded-xl text-slate-400 text-sm">
            No goals registered in Personal Model.
          </div>
        )}
      </div>
    </div>
  );
};
