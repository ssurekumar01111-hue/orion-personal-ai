import React from 'react';
import { Project } from '../../types/personal';
import { Badge } from '../common/Badge';
import { FolderGit2, GitBranch, Calendar, Folder } from 'lucide-react';

interface ProjectsPanelProps {
  projects: Project[];
  className?: string;
}

export const ProjectsPanel: React.FC<ProjectsPanelProps> = ({
  projects,
  className = '',
}) => {
  return (
    <div className={`p-6 max-w-5xl mx-auto space-y-6 ${className}`} data-testid="projects-panel">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-lg font-bold text-slate-100 tracking-tight">Projects</h2>
          <p className="text-xs text-slate-400">
            Structured workspace records stored in Orion's Personal Model V1.
          </p>
        </div>
        <Badge variant="cyan">{projects.length} Total</Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {projects.map((project) => (
          <div
            key={project.id}
            className="rounded-xl border border-slate-800 bg-orion-900/90 p-5 space-y-3 hover:border-slate-750 transition-all shadow-sm"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-cyan-950 border border-cyan-800/80 flex items-center justify-center text-cyan-400">
                  <Folder className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-semibold text-slate-200 text-sm">{project.name}</h3>
                  <span className="text-[11px] font-mono text-slate-400">ID #{project.id}</span>
                </div>
              </div>
              <Badge variant={project.status === 'active' ? 'emerald' : 'slate'}>
                {project.status}
              </Badge>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed min-h-[36px]">
              {project.description || 'No description provided.'}
            </p>

            <div className="pt-3 border-t border-slate-800/80 space-y-1.5 text-xs font-mono text-slate-400">
              {project.path && (
                <div className="flex items-center gap-2 truncate">
                  <FolderGit2 className="w-3.5 h-3.5 text-cyan-500 shrink-0" />
                  <span className="truncate" title={project.path}>
                    {project.path}
                  </span>
                </div>
              )}

              {project.repository && (
                <div className="flex items-center gap-2 truncate">
                  <GitBranch className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                  <span className="truncate">{project.repository}</span>
                </div>
              )}

              {project.created_at && (
                <div className="flex items-center gap-2 text-[11px] text-slate-500">
                  <Calendar className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                  <span>Created {new Date(project.created_at).toLocaleDateString()}</span>
                </div>
              )}
            </div>
          </div>
        ))}

        {projects.length === 0 && (
          <div className="col-span-full p-12 text-center border border-dashed border-slate-800 rounded-xl text-slate-400 text-sm">
            No projects registered in Personal Model.
          </div>
        )}
      </div>
    </div>
  );
};
