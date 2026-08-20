import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
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
