import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { AppProvider } from './state/AppContext';
import { WorkspaceProvider } from './state/Workspace';
import { ConfirmProvider } from './components/ConfirmDialog';
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('Root element #root was not found');

createRoot(container).render(
  <StrictMode>
    <WorkspaceProvider>
      <ConfirmProvider>
        <AppProvider>
          <App />
        </AppProvider>
      </ConfirmProvider>
    </WorkspaceProvider>
  </StrictMode>,
);
