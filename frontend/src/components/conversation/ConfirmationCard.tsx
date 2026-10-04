import React, { useState } from 'react';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import {
  AlertTriangle,
  CheckCircle,
  Copy,
  FileCode,
  ShieldCheck,
  XCircle,
} from 'lucide-react';

interface ConfirmationCardProps {
  confirmationId: string;
  tool: string;
  summary?: string | null;
  argumentsData?: Record<string, unknown> | null;
  onConfirm: (confirmationId: string, approved: boolean) => Promise<void>;
  status?: 'pending' | 'executed' | 'rejected' | 'error';
  result?: unknown;
  feedbackMessage?: string | null;
  className?: string;
}

export const ConfirmationCard: React.FC<ConfirmationCardProps> = ({
  confirmationId,
  tool,
  summary,
  argumentsData,
  onConfirm,
  status = 'pending',
  result,
  feedbackMessage,
  className = '',
}) => {
  const [isSubmitting, setIsSubmitting] = useState<'approve' | 'reject' | null>(null);
  const [copied, setCopied] = useState(false);

  const handleApprove = async () => {
    setIsSubmitting('approve');
    try {
      await onConfirm(confirmationId, true);
    } finally {
      setIsSubmitting(null);
    }
  };

  const handleReject = async () => {
    setIsSubmitting('reject');
    try {
      await onConfirm(confirmationId, false);
    } finally {
      setIsSubmitting(null);
    }
  };

  const copyId = () => {
    navigator.clipboard.writeText(confirmationId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const shortId = confirmationId.length > 14 ? `${confirmationId.slice(0, 10)}...` : confirmationId;

  return (
    <div
      className={`rounded-xl border border-amber-700/60 bg-amber-950/20 p-4 space-y-3.5 backdrop-blur-sm shadow-lg shadow-black/20 ${className}`}
      data-testid="confirmation-card"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-amber-800/40 pb-2.5">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded-md bg-amber-500/10 border border-amber-500/30">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
          </div>
          <div>
            <h4 className="text-xs font-semibold tracking-wide text-amber-200 uppercase font-mono">
              Action Requires Confirmation
            </h4>
            <span className="text-[11px] text-amber-400/80">
              Orion security policy paused execution for explicit user authorization.
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <Badge variant="amber">confirmation_required</Badge>
        </div>
      </div>

      {/* Target Tool and ID */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
        <div className="bg-orion-950/70 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block text-[10px] font-mono uppercase mb-0.5">
            Requested Tool
          </span>
          <span className="font-mono font-semibold text-cyan-300">{tool}</span>
        </div>

        <div className="bg-orion-950/70 p-2.5 rounded-lg border border-slate-800 flex items-center justify-between">
          <div>
            <span className="text-slate-400 block text-[10px] font-mono uppercase mb-0.5">
              Confirmation ID
            </span>
            <span className="font-mono text-slate-300" title={confirmationId}>
              {copied ? 'Copied!' : shortId}
            </span>
          </div>
          <button
            type="button"
            onClick={copyId}
            className={`p-1 rounded transition-colors ${
              copied ? 'text-emerald-400' : 'text-slate-400 hover:text-cyan-300 hover:bg-slate-800/60'
            }`}
            title="Copy Confirmation ID"
          >
            <Copy className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Summary */}
      {summary && (
        <div className="bg-orion-950/80 p-3 rounded-lg border border-slate-800/90 text-xs">
          <span className="text-slate-400 block text-[10px] font-mono uppercase mb-1">
            Operation Summary
          </span>
          <p className="text-slate-200 leading-relaxed font-mono whitespace-pre-wrap">{summary}</p>
        </div>
      )}

      {/* Structured create_skill details */}
      {tool === 'create_skill' && argumentsData && (
        <div className="bg-orion-950/80 p-3 rounded-lg border border-slate-800/90 text-xs space-y-2 font-mono">
          <div>
            <span className="text-slate-400 block text-[10px] uppercase font-semibold">Name:</span>
            <span className="text-slate-200 font-semibold">{String(argumentsData.name || '')}</span>
          </div>
          <div>
            <span className="text-slate-400 block text-[10px] uppercase font-semibold">Description:</span>
            <span className="text-slate-300">{String(argumentsData.description || '')}</span>
          </div>
          <div>
            <span className="text-slate-400 block text-[10px] uppercase font-semibold">Workflow:</span>
            <span className="text-cyan-300">
              {(() => {
                let wf = argumentsData.workflow;
                if (typeof wf === 'string') {
                  try {
                    wf = JSON.parse(wf);
                  } catch {
                    wf = null;
                  }
                }
                if (wf && typeof wf === 'object' && Array.isArray((wf as { steps?: unknown[] }).steps)) {
                  const tools = (wf as { steps: Array<{ tool?: string }> }).steps
                    .map((s) => s.tool)
                    .filter(Boolean);
                  return tools.join(' -> ') || 'Empty workflow';
                }
                return 'No workflow';
              })()}
            </span>
          </div>
        </div>
      )}

      {/* Arguments inspection */}
      {argumentsData && Object.keys(argumentsData).length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 text-[11px] font-mono text-slate-400">
            <FileCode className="w-3 h-3 text-cyan-400" />
            <span>Bound Tool Arguments (Immutable)</span>
          </div>
          <pre className="p-2.5 rounded-lg bg-orion-950 border border-slate-800 text-[11px] font-mono text-slate-300 overflow-x-auto max-h-40 whitespace-pre-wrap break-all">
            {JSON.stringify(argumentsData, null, 2)}
          </pre>
        </div>
      )}

      {/* Post-confirmation feedback state */}
      {status === 'executed' && (
        <div className="p-3 rounded-lg bg-emerald-950/30 border border-emerald-800/60 flex items-start gap-2 text-xs">
          <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
          <div className="space-y-1 w-full">
            <span className="font-semibold text-emerald-300 block">
              Action approved and executed successfully.
            </span>
            {result !== undefined && (
              <pre className="mt-1 p-2 rounded bg-orion-950 border border-emerald-900/40 text-[11px] font-mono text-emerald-300/90 overflow-x-auto max-h-36">
                {typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result)}
              </pre>
            )}
          </div>
        </div>
      )}

      {status === 'rejected' && (
        <div className="p-3 rounded-lg bg-rose-950/30 border border-rose-800/60 flex items-center gap-2 text-xs text-rose-300">
          <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{feedbackMessage || 'Action was rejected by user. Tool was not executed.'}</span>
        </div>
      )}

      {/* Action Buttons (only visible while pending) */}
      {status === 'pending' && (
        <div className="flex items-center justify-end gap-2.5 pt-1">
          <Button
            variant="danger"
            size="sm"
            onClick={handleReject}
            isLoading={isSubmitting === 'reject'}
            disabled={isSubmitting !== null}
            data-testid="reject-button"
            leftIcon={<XCircle className="w-3.5 h-3.5" />}
          >
            Reject
          </Button>

          <Button
            variant="primary"
            size="sm"
            onClick={handleApprove}
            isLoading={isSubmitting === 'approve'}
            disabled={isSubmitting !== null}
            data-testid="approve-button"
            leftIcon={<ShieldCheck className="w-3.5 h-3.5" />}
          >
            Approve Action
          </Button>
        </div>
      )}
    </div>
  );
};
