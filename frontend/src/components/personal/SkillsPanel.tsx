import React, { useState } from 'react';
import { Skill, SkillWorkflow } from '../../types/personal';
import { Badge } from '../common/Badge';
import { Wrench, ChevronDown, ChevronRight, Terminal } from 'lucide-react';

interface SkillsPanelProps {
  skills: Skill[];
  className?: string;
}

export const SkillsPanel: React.FC<SkillsPanelProps> = ({
  skills,
  className = '',
}) => {
  const [expandedSkillId, setExpandedSkillId] = useState<number | null>(null);

  const toggleExpand = (id: number) => {
    setExpandedSkillId((prev) => (prev === id ? null : id));
  };

  const parseWorkflow = (wf: string | SkillWorkflow): SkillWorkflow | null => {
    if (typeof wf === 'object' && wf !== null && 'steps' in wf) {
      return wf as SkillWorkflow;
    }
    if (typeof wf === 'string') {
      try {
        return JSON.parse(wf) as SkillWorkflow;
      } catch {
        return null;
      }
    }
    return null;
  };

  return (
    <div className={`p-6 max-w-5xl mx-auto space-y-6 ${className}`} data-testid="skills-panel">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-slate-100 tracking-tight">Reusable Skills</h2>
          <p className="text-xs text-slate-400">
            Explicit, structured multi-step workflows stored in Orion (Phase 4B).
          </p>
        </div>
        <Badge variant="cyan">{skills.length} Registered</Badge>
      </div>

      <div className="space-y-3">
        {skills.map((skill) => {
          const isExpanded = expandedSkillId === skill.id;
          const parsed = parseWorkflow(skill.workflow);
          const stepsCount = parsed?.steps?.length || 0;

          return (
            <div
              key={skill.id}
              className="rounded-xl border border-slate-800 bg-orion-900/80 p-4 hover:border-slate-750 transition-all space-y-3"
            >
              <div
                className="flex items-start justify-between gap-3 cursor-pointer select-none"
                onClick={() => toggleExpand(skill.id)}
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-lg bg-cyan-950/70 border border-cyan-800 flex items-center justify-center shrink-0 text-cyan-400 mt-0.5">
                    <Wrench className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-slate-200 text-sm font-mono flex items-center gap-2">
                      <span>{skill.name}</span>
                    </h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {skill.description || 'No description provided.'}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2.5 shrink-0">
                  <Badge variant="cyan">{stepsCount} steps</Badge>
                  <button
                    type="button"
                    className="p-1 rounded text-slate-400 hover:text-slate-200"
                    aria-label="Toggle workflow steps"
                  >
                    {isExpanded ? (
                      <ChevronDown className="w-4 h-4" />
                    ) : (
                      <ChevronRight className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>

              {/* Workflow Breakdown Drawer */}
              {isExpanded && (
                <div className="pt-3 border-t border-slate-800/80 space-y-3">
                  <span className="text-[11px] font-mono text-slate-400 block uppercase font-semibold">
                    Workflow Sequence
                  </span>

                  {parsed && parsed.steps ? (
                    <div className="space-y-2">
                      {parsed.steps.map((st, i) => (
                        <div
                          key={i}
                          className="p-2.5 rounded-lg bg-orion-950 border border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs font-mono"
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-slate-500 text-[11px]">{i + 1}.</span>
                            <Terminal className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                            <span className="text-cyan-300 font-medium">{st.tool}</span>
                          </div>

                          {st.arguments && Object.keys(st.arguments).length > 0 && (
                            <pre className="text-[11px] text-slate-400 bg-orion-900/80 px-2 py-1 rounded border border-slate-800 truncate max-w-md">
                              {JSON.stringify(st.arguments)}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <pre className="p-3 rounded-lg bg-orion-950 border border-slate-800 text-xs font-mono text-slate-300 overflow-x-auto">
                      {typeof skill.workflow === 'string'
                        ? skill.workflow
                        : JSON.stringify(skill.workflow, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {skills.length === 0 && (
          <div className="p-12 text-center border border-dashed border-slate-800 rounded-xl text-slate-400 text-sm">
            No reusable skills saved yet. You can ask Orion to "Save this workflow as a skill" in Agent Mode.
          </div>
        )}
      </div>
    </div>
  );
};
