import React from 'react';
import { Task } from '../../types/personal';
import { Badge } from '../common/Badge';
import { CheckSquare } from 'lucide-react';

interface TasksPanelProps {
  tasks: Task[];
  className?: string;
}

export const TasksPanel: React.FC<TasksPanelProps> = ({
  tasks,
  className = '',
}) => {
  return (
    <div className={`p-6 max-w-5xl mx-auto space-y-6 ${className}`} data-testid="tasks-panel">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-slate-100 tracking-tight">Tasks</h2>
          <p className="text-xs text-slate-400">
            Action items and deliverables tracked with priorities and goals.
          </p>
        </div>
        <Badge variant="cyan">{tasks.length} Tasks</Badge>
      </div>

      <div className="space-y-2.5">
        {tasks.map((task) => {
          const isDone = task.status === 'completed';

          return (
            <div
              key={task.id}
              className={`rounded-xl border border-slate-800 bg-orion-900/80 p-4 flex items-center justify-between gap-4 transition-all ${
                isDone ? 'opacity-60 bg-orion-950/40' : 'hover:border-slate-750'
              }`}
            >
              <div className="flex items-center gap-3">
                <div
                  className={`w-6 h-6 rounded-md flex items-center justify-center shrink-0 border ${
                    isDone
                      ? 'bg-emerald-950/60 border-emerald-800 text-emerald-400'
                      : 'border-slate-700 bg-orion-850 text-slate-500'
                  }`}
                >
                  <CheckSquare className="w-3.5 h-3.5" />
                </div>

                <div>
                  <h4
                    className={`text-sm font-medium ${
                      isDone ? 'line-through text-slate-400' : 'text-slate-200'
                    }`}
                  >
                    {task.title}
                  </h4>
                  {task.description && (
                    <p className="text-xs text-slate-400 mt-0.5">{task.description}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2.5 shrink-0">
                {task.priority && (
                  <Badge
                    variant={
                      task.priority === 'urgent' || task.priority === 'high'
                        ? 'amber'
                        : 'slate'
                    }
                    size="sm"
                  >
                    {task.priority}
                  </Badge>
                )}

                <Badge variant={isDone ? 'emerald' : 'cyan'} size="sm">
                  {task.status}
                </Badge>
              </div>
            </div>
          );
        })}

        {tasks.length === 0 && (
          <div className="p-12 text-center border border-dashed border-slate-800 rounded-xl text-slate-400 text-sm">
            No tasks registered in Personal Model.
          </div>
        )}
      </div>
    </div>
  );
};
