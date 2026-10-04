import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  variant?: 'default' | 'highlight' | 'warning' | 'danger';
}

const variantBorders: Record<string, string> = {
  default: 'border-slate-800 bg-orion-900/90 hover:border-slate-750',
  highlight: 'border-cyan-800/60 bg-orion-900/95 ring-1 ring-cyan-500/20',
  warning: 'border-amber-700/60 bg-amber-950/20 ring-1 ring-amber-500/20',
  danger: 'border-rose-700/60 bg-rose-950/20 ring-1 ring-rose-500/20',
};

export const Card: React.FC<CardProps> = ({
  children,
  className = '',
  onClick,
  variant = 'default',
}) => {
  return (
    <div
      onClick={onClick}
      className={`rounded-xl border backdrop-blur-sm p-4 transition-all duration-150 ${variantBorders[variant]} ${
        onClick ? 'cursor-pointer' : ''
      } ${className}`}
    >
      {children}
    </div>
  );
};
