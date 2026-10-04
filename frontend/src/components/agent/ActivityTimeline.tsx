import React, { useState } from 'react';
import { AgentStep, StepStatusType } from '../../types/agent';
import { Badge } from '../common/Badge';
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  Eye,
  ShieldAlert,
  Sparkles,
  Terminal,
  XCircle,
} from 'lucide-react';

interface ActivityTimelineProps {
  steps: AgentStep[];
  isStreaming?: boolean;
  className?: string;
  totalIterations?: number;
}

export const ActivityTimeline: React.FC<ActivityTimelineProps> = ({
  steps,
  isStreaming = false,
  className = '',
  totalIterations = 5,
}) => {
  const [expandedSteps, setExpandedSteps] = useState<Record<number, boolean>>({});

  const toggleStep = (idx: number) => {
    setExpandedSteps((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  if (!steps || steps.length === 0) {
    return null;
  }

  const getStepIcon = (action: string, status: StepStatusType) => {
    if (status === 'error') return <XCircle className="w-4 h-4 text-rose-400" />;
    if (status === 'blocked') return <ShieldAlert className="w-4 h-4 text-amber-400" />;
    if (status === 'confirmation_required') return <ShieldAlert className="w-4 h-4 text-amber-400" />;
    if (action === 'respond' || status === 'completed') return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    if (action === 'tool' || status === 'executed') return <Terminal className="w-4 h-4 text-cyan-400" />;
    if (action === 'plan') return <Brain className="w-4 h-4 text-purple-400" />;
    if (action === 'observe') return <Eye className="w-4 h-4 text-blue-400" />;
    return <Sparkles className="w-4 h-4 text-cyan-400" />;
  };

  const getStatusBadge = (status: StepStatusType, permission?: string) => {
    switch (status) {
      case 'executed':
        return <Badge variant="emerald">executed</Badge>;
      case 'confirmation_required':
        return <Badge variant="amber">confirmation required</Badge>;
      case 'blocked':
        return <Badge variant="rose">blocked</Badge>;
      case 'error':
        return <Badge variant="rose">error</Badge>;
      case 'completed':
        return <Badge variant="emerald">completed</Badge>;
      case 'repeated_call':
        return <Badge variant="amber">repeated call stopped</Badge>;
      default:
        if (permission) {
          return <Badge variant="slate">{permission}</Badge>;
        }
        return <Badge variant="slate">{status}</Badge>;
    }
  };

  return (
    <div className={`rounded-xl border border-slate-800 bg-orion-900/80 p-4 space-y-3 ${className}`}>
      <div className="flex items-center justify-between pb-2 border-b border-slate-800/80">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-cyan-400" />
          <span className="text-xs font-mono font-semibold tracking-wider text-slate-300 uppercase">
            Agent Activity Timeline
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-slate-400">
            Bounded loop: {steps.length}/{totalIterations} steps
          </span>
          {isStreaming && (
            <span className="flex items-center gap-1 text-[11px] font-mono text-cyan-400 animate-pulse">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
              active
            </span>
          )}
        </div>
      </div>

      <div className="relative pl-4 space-y-3 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-[1px] before:bg-slate-800">
        {steps.map((step, idx) => {
          const isExpanded = Boolean(expandedSteps[idx]);
          const hasDetails = Boolean(
            (step.arguments && Object.keys(step.arguments).length > 0) ||
            step.error ||
            step.result ||
            step.confirmation_id
          );

          return (
            <div key={idx} className="relative group text-xs">
              {/* Step indicator dot */}
              <div className="absolute -left-[1.35rem] top-1 p-0.5 rounded-full bg-orion-950 border border-slate-700">
                {getStepIcon(step.action, step.status)}
              </div>

              <div className="rounded-lg border border-slate-800/80 bg-orion-850/60 hover:border-slate-750 transition-colors p-2.5">
                <div
                  className={`flex items-center justify-between gap-2 ${
                    hasDetails ? 'cursor-pointer select-none' : ''
                  }`}
                  onClick={() => hasDetails && toggleStep(idx)}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-slate-400 text-[11px]">
                      Step {step.step || idx + 1}:
                    </span>

                    <span className="font-mono font-semibold uppercase text-slate-200">
                      {step.action === 'tool' ? `TOOL → ${step.tool}` : step.action}
                    </span>

                    {getStatusBadge(step.status, step.permission)}
                  </div>

                  <div className="flex items-center gap-2">
                    {step.confirmation_id && (
                      <span className="text-[10px] font-mono text-amber-400/90 bg-amber-950/40 px-1.5 py-0.5 rounded border border-amber-900/60">
                        ID: {step.confirmation_id.slice(0, 10)}...
                      </span>
                    )}
                    {hasDetails && (
                      <button
                        type="button"
                        className="text-slate-400 hover:text-slate-200 transition-colors p-0.5"
                        aria-label="Toggle step details"
                      >
                        {isExpanded ? (
                          <ChevronDown className="w-3.5 h-3.5" />
                        ) : (
                          <ChevronRight className="w-3.5 h-3.5" />
                        )}
                      </button>
                    )}
                  </div>
                </div>

                {/* Collapsible details for arguments or results */}
                {isExpanded && hasDetails && (
                  <div className="mt-2.5 pt-2 border-t border-slate-800/80 space-y-2">
                    {step.arguments && Object.keys(step.arguments).length > 0 && (
                      <div>
                        <div className="flex items-center gap-1 text-[11px] font-mono text-slate-400 mb-1">
                          <Code2 className="w-3 h-3 text-cyan-400" />
                          <span>Arguments</span>
                        </div>
                        <pre className="p-2 rounded bg-orion-950 border border-slate-800 text-[11px] font-mono text-slate-300 overflow-x-auto max-h-48 whitespace-pre-wrap break-all">
                          {JSON.stringify(step.arguments, null, 2)}
                        </pre>
                      </div>
                    )}

                    {step.error && (
                      <div className="p-2 rounded bg-rose-950/30 border border-rose-900/60 text-rose-300 text-[11px] font-mono">
                        <span className="font-semibold">Error:</span> {step.error}
                      </div>
                    )}

                    {step.result !== undefined && (
                      <div>
                        <div className="flex items-center gap-1 text-[11px] font-mono text-slate-400 mb-1">
                          <Eye className="w-3 h-3 text-emerald-400" />
                          <span>Observation Result</span>
                        </div>
                        <pre className="p-2 rounded bg-orion-950 border border-slate-800 text-[11px] font-mono text-emerald-300/90 overflow-x-auto max-h-48 whitespace-pre-wrap break-all">
                          {typeof step.result === 'object'
                            ? JSON.stringify(step.result, null, 2)
                            : String(step.result)}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
