import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
// Self-hosted so the admin does not depend on a third-party font host at
// render time. A single variable file covers the whole 200-800 weight axis,
// which is every weight this stylesheet uses.
import '@fontsource-variable/plus-jakarta-sans';
import './index.css';
import App from './App';
import { AdminStoreProvider } from './store/AdminStore';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AdminStoreProvider>
      <App />
    </AdminStoreProvider>
  </StrictMode>,
);
