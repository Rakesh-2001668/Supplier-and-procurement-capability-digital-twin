import React from 'react';

interface PageHeaderProps {
  title: string;
  subtitle: string;
  badge?: string;
  actions?: React.ReactNode;
}

export function PageHeader({ title, subtitle, badge, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col md:flex-row md:items-start md:justify-between mb-8">
      <div>
        <div className="text-[10px] text-[var(--text-secondary)] uppercase tracking-widest font-bold mb-1">COMMAND CENTRE</div>
        <div className="flex items-center space-x-3 mb-2">
            <h1 className="text-3xl font-bold text-[var(--text-primary)] tracking-tight">{title}</h1>
            {badge && <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs font-bold rounded">{badge}</span>}
        </div>
        <p className="text-[var(--text-secondary)]">{subtitle}</p>
      </div>
      <div className="mt-4 md:mt-0 flex items-center space-x-3">
        {actions}
      </div>
    </div>
  );
}
