import React, { useState } from 'react';
import { Skill, SkillWorkflow, SkillExecution, SkillProposal, SkillVersion } from '../../types/personal';
import { Badge } from '../common/Badge';
import {
  Wrench,
  ChevronDown,
  ChevronRight,
  Terminal,
  History,
  Sparkles,
  RotateCcw,
  Check,
  X,
  Clock,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react';
import {
  getSkillExecutions,
  getSkillProposals,
  approveSkillProposal,
  rejectSkillProposal,
  getSkillVersions,
  rollbackSkill,
} from '../../api/personal';

interface SkillsPanelProps {
  skills: Skill[];
  onSkillUpdated?: () => void;
  className?: string;
}

export const SkillsPanel: React.FC<SkillsPanelProps> = ({
  skills,
  onSkillUpdated,
  className = '',
}) => {
  const [expandedSkillId, setExpandedSkillId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<Record<number, 'workflow' | 'history' | 'proposals' | 'versions'>>({});
  const [executions, setExecutions] = useState<Record<number, SkillExecution[]>>({});
  const [proposals, setProposals] = useState<Record<number, SkillProposal[]>>({});
  const [versions, setVersions] = useState<Record<number, SkillVersion[]>>({});
  const [, setLoading] = useState<Record<number, boolean>>({});

  const toggleExpand = (id: number) => {
    setExpandedSkillId((prev) => (prev === id ? null : id));
  };

  const loadSkillDetails = async (skillId: number) => {
    setLoading((prev) => ({ ...prev, [skillId]: true }));
    try {
      const [execs, props, vers] = await Promise.allSettled([
        getSkillExecutions(skillId, 10),
        getSkillProposals(skillId),
        getSkillVersions(skillId),
      ]);
      if (execs.status === 'fulfilled') {
        setExecutions((prev) => ({ ...prev, [skillId]: execs.value }));
      }
      if (props.status === 'fulfilled') {
        setProposals((prev) => ({ ...prev, [skillId]: props.value }));
      }
      if (vers.status === 'fulfilled') {
        setVersions((prev) => ({ ...prev, [skillId]: vers.value }));
      }
    } catch {
      // Safe fallback in offline / test environments
    } finally {
      setLoading((prev) => ({ ...prev, [skillId]: false }));
    }
  };

  const handleApprove = async (skillId: number, proposalId: number) => {
    try {
      await approveSkillProposal(skillId, proposalId);
      await loadSkillDetails(skillId);
      if (onSkillUpdated) onSkillUpdated();
    } catch (err) {
      console.error('Failed to approve proposal:', err);
    }
  };

  const handleReject = async (skillId: number, proposalId: number) => {
    try {
      await rejectSkillProposal(skillId, proposalId);
      await loadSkillDetails(skillId);
    } catch (err) {
      console.error('Failed to reject proposal:', err);
    }
  };

  const handleRollback = async (skillId: number, versionNumber: number) => {
    try {
      await rollbackSkill(skillId, versionNumber);
      await loadSkillDetails(skillId);
      if (onSkillUpdated) onSkillUpdated();
    } catch (err) {
      console.error('Failed to rollback skill:', err);
    }
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
          <h2 className="text-lg font-bold text-slate-100 tracking-tight">Reusable Skills & Learning</h2>
          <p className="text-xs text-slate-400">
            Multi-step workflows with performance tracking, automated improvement proposals, and rollback history.
          </p>
        </div>
        <Badge variant="cyan">{skills.length} Registered</Badge>
      </div>

      <div className="space-y-4">
        {skills.map((skill) => {
          const isExpanded = expandedSkillId === skill.id;
          const parsed = parseWorkflow(skill.workflow);
          const stepsCount = parsed?.steps?.length || 0;
          const currentTab = activeTab[skill.id] || 'workflow';
          const skillProps = proposals[skill.id] || [];
          const pendingProps = skillProps.filter((p) => p.status === 'pending');
          const skillExecs = executions[skill.id] || [];
          const skillVers = versions[skill.id] || [];

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
                      {pendingProps.length > 0 && (
                        <span className="flex items-center gap-1 text-[10px] font-mono bg-amber-500/20 text-amber-300 border border-amber-500/30 px-1.5 py-0.2 rounded-full">
                          <Sparkles className="w-3 h-3 text-amber-400" />
                          {pendingProps.length} proposal
                        </span>
                      )}
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

              {/* Collapsible Details Drawer */}
              {isExpanded && (
                <div className="pt-3 border-t border-slate-800/80 space-y-3">
                  {/* Sub-tabs */}
                  <div className="flex items-center gap-2 border-b border-slate-800 pb-2">
                    <button
                      type="button"
                      onClick={() => setActiveTab((t) => ({ ...t, [skill.id]: 'workflow' }))}
                      className={`text-xs font-mono px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
                        currentTab === 'workflow'
                          ? 'bg-slate-800 text-cyan-300'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      <Terminal className="w-3.5 h-3.5" />
                      Workflow ({stepsCount})
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setActiveTab((t) => ({ ...t, [skill.id]: 'history' }));
                        loadSkillDetails(skill.id);
                      }}
                      className={`text-xs font-mono px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
                        currentTab === 'history'
                          ? 'bg-slate-800 text-cyan-300'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      <History className="w-3.5 h-3.5" />
                      History ({skillExecs.length})
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setActiveTab((t) => ({ ...t, [skill.id]: 'proposals' }));
                        loadSkillDetails(skill.id);
                      }}
                      className={`text-xs font-mono px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
                        currentTab === 'proposals'
                          ? 'bg-slate-800 text-amber-300'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      Proposals ({pendingProps.length})
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setActiveTab((t) => ({ ...t, [skill.id]: 'versions' }));
                        loadSkillDetails(skill.id);
                      }}
                      className={`text-xs font-mono px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
                        currentTab === 'versions'
                          ? 'bg-slate-800 text-cyan-300'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      Versions ({skillVers.length})
                    </button>
                  </div>

                  {/* TAB 1: WORKFLOW */}
                  {currentTab === 'workflow' && (
                    <div className="space-y-2">
                      {parsed && parsed.steps ? (
                        parsed.steps.map((st, i) => (
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
                        ))
                      ) : (
                        <pre className="p-3 rounded-lg bg-orion-950 border border-slate-800 text-xs font-mono text-slate-300 overflow-x-auto">
                          {typeof skill.workflow === 'string'
                            ? skill.workflow
                            : JSON.stringify(skill.workflow, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}

                  {/* TAB 2: EXECUTION HISTORY */}
                  {currentTab === 'history' && (
                    <div className="space-y-2">
                      {skillExecs.length > 0 ? (
                        skillExecs.map((exec) => (
                          <div
                            key={exec.id}
                            className="p-2.5 rounded-lg bg-orion-950 border border-slate-800 flex items-center justify-between gap-3 text-xs font-mono"
                          >
                            <div className="flex items-center gap-2">
                              {exec.status === 'completed' ? (
                                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                              ) : (
                                <AlertTriangle className="w-4 h-4 text-rose-400" />
                              )}
                              <span className="text-slate-200">Execution #{exec.id}</span>
                              <Badge
                                variant={exec.status === 'completed' ? 'emerald' : 'rose'}
                                size="sm"
                              >
                                {exec.status}
                              </Badge>
                              {exec.failure_reason && (
                                <span className="text-slate-400 text-[11px] truncate max-w-xs">
                                  ({exec.failure_reason})
                                </span>
                              )}
                            </div>

                            <div className="flex items-center gap-3 text-slate-500 text-[11px]">
                              {exec.duration_ms > 0 && (
                                <span className="flex items-center gap-1">
                                  <Clock className="w-3 h-3" />
                                  {exec.duration_ms.toFixed(1)}ms
                                </span>
                              )}
                              <span>
                                {exec.created_at ? new Date(exec.created_at).toLocaleTimeString() : ''}
                              </span>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="p-4 text-center text-xs text-slate-500 font-mono">
                          No executions recorded yet. Run this skill to collect performance history.
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 3: PROPOSALS */}
                  {currentTab === 'proposals' && (
                    <div className="space-y-3">
                      {skillProps.length > 0 ? (
                        skillProps.map((prop) => {
                          const propWf = parseWorkflow(prop.proposed_workflow);
                          return (
                            <div
                              key={prop.id}
                              className="p-3.5 rounded-lg bg-orion-950 border border-slate-800 space-y-2.5"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <h4 className="font-semibold text-slate-200 text-xs font-mono flex items-center gap-2">
                                    <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                                    <span>{prop.title}</span>
                                    <Badge
                                      variant={
                                        prop.status === 'approved'
                                          ? 'emerald'
                                          : prop.status === 'rejected'
                                          ? 'rose'
                                          : 'amber'
                                      }
                                      size="sm"
                                    >
                                      {prop.status}
                                    </Badge>
                                  </h4>
                                  <p className="text-xs text-slate-400 mt-1">{prop.rationale}</p>
                                </div>

                                {prop.status === 'pending' && (
                                  <div className="flex items-center gap-2 shrink-0">
                                    <button
                                      type="button"
                                      onClick={() => handleApprove(skill.id, prop.id)}
                                      className="px-2.5 py-1 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30 text-xs font-mono flex items-center gap-1 transition-colors"
                                    >
                                      <Check className="w-3.5 h-3.5" />
                                      Approve
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => handleReject(skill.id, prop.id)}
                                      className="px-2.5 py-1 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30 hover:bg-rose-500/30 text-xs font-mono flex items-center gap-1 transition-colors"
                                    >
                                      <X className="w-3.5 h-3.5" />
                                      Reject
                                    </button>
                                  </div>
                                )}
                              </div>

                              {propWf && propWf.steps && (
                                <div className="space-y-1 pt-1 border-t border-slate-900">
                                  <span className="text-[10px] font-mono text-slate-500 uppercase">
                                    Proposed Steps ({propWf.steps.length})
                                  </span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {propWf.steps.map((st, i) => (
                                      <span
                                        key={i}
                                        className="text-[11px] font-mono bg-orion-900 text-slate-300 px-2 py-0.5 rounded border border-slate-800"
                                      >
                                        {i + 1}. {st.tool}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })
                      ) : (
                        <div className="p-4 text-center text-xs text-slate-500 font-mono">
                          No pending improvement proposals. Orion will generate proposals automatically if failures occur.
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 4: VERSIONS & ROLLBACK */}
                  {currentTab === 'versions' && (
                    <div className="space-y-2">
                      {skillVers.length > 0 ? (
                        skillVers.map((ver) => (
                          <div
                            key={ver.id}
                            className="p-2.5 rounded-lg bg-orion-950 border border-slate-800 flex items-center justify-between gap-3 text-xs font-mono"
                          >
                            <div>
                              <span className="text-cyan-400 font-bold mr-2">v{ver.version_number}</span>
                              <span className="text-slate-300">
                                {ver.change_summary || 'Snapshot'}
                              </span>
                            </div>

                            <button
                              type="button"
                              onClick={() => handleRollback(skill.id, ver.version_number)}
                              className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 hover:text-cyan-300 border border-slate-700 text-[11px] font-mono flex items-center gap-1 transition-colors"
                            >
                              <RotateCcw className="w-3 h-3" />
                              Rollback
                            </button>
                          </div>
                        ))
                      ) : (
                        <div className="p-4 text-center text-xs text-slate-500 font-mono">
                          No previous versions recorded yet. Versions are snapshotted automatically on creation and approval.
                        </div>
                      )}
                    </div>
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
