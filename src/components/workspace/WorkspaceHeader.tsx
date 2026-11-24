import React from 'react';
import type { MistUser as User, MistProject, ViewportSize, WorkspaceViewMode } from '../../types/mist';
import MobileWorkspaceHeader from './MobileWorkspaceHeader';
import DesktopWorkspaceHeader from './DesktopWorkspaceHeader';

interface WorkspaceHeaderProps {
  user: User | null;
  project: MistProject;
  viewMode: WorkspaceViewMode;
  viewport: ViewportSize;
  shortProviderLabel: string;
  providerApiKey?: string;
  activePane: 'chat' | 'preview';
  onBackHome: () => void;
  onUpdateProjectName: (name: string) => void;
  onSetViewMode: (mode: WorkspaceViewMode) => void;
  onSetViewport: (viewport: ViewportSize) => void;
  onSetActivePane: (pane: 'chat' | 'preview') => void;
  onOpenMobileMore: () => void;
  onOpenVoiceChat: () => void;
  onOpenProviders: () => void;
  onDuplicateProject: () => void;
  onExportZip: () => void;
  onOpenDeploy: () => void;
  onOpenSettings: () => void;
  onOpenAccount: () => void;
}

export default function WorkspaceHeader(props: WorkspaceHeaderProps) {
  return (
    <>
      <MobileWorkspaceHeader
        project={props.project}
        shortProviderLabel={props.shortProviderLabel}
        activePane={props.activePane}
        onBackHome={props.onBackHome}
        onSetActivePane={props.onSetActivePane}
        onOpenDeploy={props.onOpenDeploy}
        onOpenMobileMore={props.onOpenMobileMore}
      />
      <DesktopWorkspaceHeader
        user={props.user}
        project={props.project}
        viewMode={props.viewMode}
        viewport={props.viewport}
        shortProviderLabel={props.shortProviderLabel}
        providerApiKey={props.providerApiKey}
        onBackHome={props.onBackHome}
        onUpdateProjectName={props.onUpdateProjectName}
        onSetViewMode={props.onSetViewMode}
        onSetViewport={props.onSetViewport}
        onOpenVoiceChat={props.onOpenVoiceChat}
        onOpenProviders={props.onOpenProviders}
        onDuplicateProject={props.onDuplicateProject}
        onExportZip={props.onExportZip}
        onOpenDeploy={props.onOpenDeploy}
        onOpenSettings={props.onOpenSettings}
        onOpenAccount={props.onOpenAccount}
      />
    </>
  );
}
