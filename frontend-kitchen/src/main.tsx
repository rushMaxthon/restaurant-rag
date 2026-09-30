import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import './index.css'
import { App } from './App'
import { AuthProvider } from './lib/auth'

/**
 * One client for the app.
 *
 * Retries are off by default here: every query on this board polls on a short
 * interval anyway, so a failed request is already about to be retried, and
 * stacking react-query's own backoff on top of that only delays the moment the
 * header can honestly say "not updating".
 */
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: true } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
