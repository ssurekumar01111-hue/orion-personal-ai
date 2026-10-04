import React from 'react';

export type BadgeVariant =
  | 'default'
  | 'cyan'
  | 'emerald'
  | 'amber'
  | 'rose'
  | 'purple'
  | 'blue'
  | 'slate';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-slate-800 text-slate-300 border-slate-700',
  cyan: 'bg-cyan-950/70 text-cyan-300 border-cyan-800/80',
  emerald: 'bg-emerald-950/70 text-emerald-300 border-emerald-800/80',
  amber: 'bg-amber-950/70 text-amber-300 border-amber-800/80',
  rose: 'bg-rose-950/70 text-rose-300 border-rose-800/80',
  purple: 'bg-purple-950/70 text-purple-300 border-purple-800/80',
  blue: 'bg-blue-950/70 text-blue-300 border-blue-800/80',
  slate: 'bg-slate-850 text-slate-400 border-slate-750',
};

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'sm',
  className = '',
}) => {
  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs';

  return (
    <span
      className={`inline-flex items-center font-mono font-medium rounded-md border tracking-tight ${sizeClasses} ${variantStyles[variant]} ${className}`}
    >
      {children}
    </span>
  );
};
