import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Deliberately plain, and deliberately not TanStack Start.
 *
 * A kitchen board is a logged-in screen on a tablet on a wall. It has no SEO,
 * no link previews and no anonymous first paint to optimise, so server
 * rendering would be cost with no benefit — which is why this is Vite and
 * React rather than the stack `frontend-customer` runs.
 *
 * 5175 because 5173 and 5174 are the customer and admin apps, and all three
 * are in the backend's default CORS list.
 */
export default defineConfig({
  plugins: [react()],
  server: { port: 5175, strictPort: true },
})
