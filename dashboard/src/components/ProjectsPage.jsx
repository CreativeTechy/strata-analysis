import { useLocation } from 'react-router-dom';
import ProjectWizard from './ProjectWizard.jsx';
import ProjectsListView from './ProjectsListView.jsx';

// Routed at /projects, /projects/new, and /projects/:projectId/edit - picks
// between the project browser and the create/edit wizard. Each is its own
// component (ProjectsListView / ProjectWizard) so switching between the list
// and the wizard remounts whichever one wasn't showing, which is what resets
// the wizard's draft/document-pipeline state when the user navigates away.
export default function ProjectsPage({
  projects = [],
  users = [],
  onCreateProject,
  onUpdateProject,
  isLoadingProjects,
}) {
  const location = useLocation();
  const isFormRoute = location.pathname.endsWith('/new') || location.pathname.endsWith('/edit');

  if (isFormRoute) {
    return (
      <ProjectWizard
        projects={projects}
        users={users}
        onCreateProject={onCreateProject}
        onUpdateProject={onUpdateProject}
      />
    );
  }

  return <ProjectsListView projects={projects} isLoadingProjects={isLoadingProjects} />;
}
