import React from 'react';
import { Project, Goal, Task, Skill } from '../../types/personal';
import { ProviderType } from '../../types/api';
import { Badge } from '../common/Badge';
import { FolderGit2, Layers } from 'lucide-react';

interface RightSidebarProps {
  projects: Project[];
  goals: Goal[];
  tasks: Task[];
  skills: Skill[];
  activeProvider: ProviderType;
  activeModel?: string;
  className?: string;
}

export const RightSidebar: React.FC<RightSidebarProps> = ({
  projects,
  goals,
  tasks,
  skills,
  activeProvider,
  activeModel,
  className = '',
}) => {
  const activeProject = projects.find((p) => p.status === 'active') || projects[0];
  const pendingTasks = tasks.filter((t) => t.status !== 'completed').slice(0, 4);
  const activeGoals = goals.filter((g) => g.status !== 'completed').slice(0, 3);

  return (
    <aside
      className={`w-72 border-l border-slate-800 bg-orion-950 flex flex-col h-full shrink-0 overflow-y-auto ${className}`}
      data-testid="right-sidebar"
    >
      {/* Header */}
      <div className="p-4 border-b border-slate-800/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-cyan-400" />
          <h2 className="text-xs font-mono font-semibold tracking-wider text-slate-200 uppercase">
            Personal Context
          </h2>
        </div>
        <span className="text-[10px] font-mono text-cyan-400/90 bg-cyan-950/60 border border-cyan-800/60 px-1.5 py-0.5 rounded">
          SNAPSHOT V1
        </span>
      </div>

      <div className="p-4 space-y-5 text-xs">
        {/* Active Project Card */}
        <div className="space-y-1.5">
          <span className="text-[10px] font-mono uppercase text-slate-400 block font-semibold">
            Active Project
          </span>
          {activeProject ? (
            <div className="p-3 rounded-xl border border-slate-800 bg-orion-900/80 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200">{activeProject.name}</span>
                <Badge variant={activeProject.status === 'active' ? 'emerald' : 'slate'}>
                  {activeProject.status}
                </Badge>
              </div>

              {activeProject.description && (
                <p className="text-[11px] text-slate-400 line-clamp-2">
                  {activeProject.description}
                </p>
              )}

              {activeProject.path && (
                <div className="pt-1.5 border-t border-slate-800/80 flex items-center gap-1.5 text-[10px] font-mono text-slate-400 truncate">
                  <FolderGit2 className="w-3 h-3 text-cyan-500 shrink-0" />
                  <span className="truncate" title={activeProject.path}>
                    {activeProject.path}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <div className="p-3 rounded-lg border border-dashed border-slate-800 text-slate-400 text-center italic">
              No active project assigned
            </div>
          )}
        </div>

        {/* Goals Snapshot */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold">
              Current Goals ({goals.length})
            </span>
          </div>

          <div className="space-y-1.5">
            {activeGoals.map((goal) => (
              <div
                key={goal.id}
                className="p-2.5 rounded-lg border border-slate-800/80 bg-orion-900/40 space-y-1"
              >
                <div className="flex items-center justify-between gap-1.5">
                  <span className="font-medium text-slate-200 text-[11px] truncate">
                    {goal.title}
                  </span>
                  <Badge
                    variant={
                      goal.status === 'completed'
                        ? 'emerald'
                        : goal.status === 'in_progress' || goal.status === 'active'
                        ? 'cyan'
                        : 'slate'
                    }
                    size="sm"
                  >
                    {goal.status}
                  </Badge>
                </div>
                {goal.description && (
                  <p className="text-[10px] text-slate-400 line-clamp-1">{goal.description}</p>
                )}
              </div>
            ))}

            {activeGoals.length === 0 && (
              <div className="text-[11px] text-slate-400 italic">
                {goals.length === 0 ? 'No goals registered' : 'All goals completed'}
              </div>
            )}
          </div>
        </div>

        {/* Tasks Snapshot */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold">
              Pending Tasks ({tasks.length})
            </span>
          </div>

          <div className="space-y-1.5">
            {pendingTasks.map((task) => (
              <div
                key={task.id}
                className="p-2 rounded-lg border border-slate-800/80 bg-orion-900/40 flex items-start justify-between gap-2"
              >
                <div className="truncate flex-1">
                  <span className="text-[11px] text-slate-200 block truncate font-medium">
                    {task.title}
                  </span>
                  <span className="text-[10px] font-mono text-slate-400">{task.status}</span>
                </div>

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
              </div>
            ))}

            {pendingTasks.length === 0 && (
              <div className="text-[11px] text-slate-400 italic">
                {tasks.length === 0 ? 'No tasks registered' : 'All tasks completed'}
              </div>
            )}
          </div>
        </div>

        {/* Reusable Skills Snapshot */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold">
              Stored Skills ({skills.length})
            </span>
          </div>

          <div className="space-y-1">
            {skills.slice(0, 3).map((skill) => (
              <div
                key={skill.id}
                className="p-2 rounded-lg border border-slate-800/60 bg-orion-900/30 flex items-center justify-between gap-1.5"
              >
                <div className="truncate flex-1">
                  <span className="text-[11px] font-mono text-cyan-300 block truncate">
                    {skill.name}
                  </span>
                </div>
                <Badge variant="cyan" size="sm">
                  skill
                </Badge>
              </div>
            ))}

            {skills.length === 0 && (
              <div className="text-[11px] text-slate-400 italic">No skills registered yet</div>
            )}
          </div>
        </div>

        {/* Runtime Status */}
        <div className="pt-3 border-t border-slate-800 space-y-2 text-[11px] font-mono">
          <span className="text-[10px] font-mono uppercase text-slate-400 block font-semibold">
            Execution Guardrails
          </span>

          <div className="space-y-1 text-slate-400 bg-orion-900/60 p-2.5 rounded-lg border border-slate-800">
            <div className="flex justify-between">
              <span>Agent Limit:</span>
              <span className="text-cyan-400 font-medium">5 iterations</span>
            </div>
            <div className="flex justify-between">
              <span>Mutating Tools:</span>
              <span className="text-amber-400 font-medium">confirmation required</span>
            </div>
            <div className="flex justify-between">
              <span>Shell Execution:</span>
              <span className="text-slate-300">allowlisted (no subshell)</span>
            </div>
            <div className="flex justify-between">
              <span>Provider:</span>
              <span className="text-cyan-300 uppercase">{activeProvider}</span>
            </div>
            {activeModel && (
              <div className="flex justify-between truncate">
                <span>Model:</span>
                <span className="text-slate-300 truncate max-w-[120px]" title={activeModel}>
                  {activeModel}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
};
