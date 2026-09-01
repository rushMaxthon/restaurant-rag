import App from './App';
import { AppStoreProvider } from './store/AppStore';
import { useAppConfig } from './store/useAppConfig';
import { ThemeProvider } from './theme';

/**
 * Sits between the two providers because the palette is built from a value the
 * config provider resolves: the restaurant's own brand colour.
 *
 * In its own file rather than in `main.tsx`, so the entry point stays a mount
 * call and this stays fast-refreshable.
 */
export function AppRoot() {
  const { brandColor } = useAppConfig();
  return (
    <ThemeProvider brandColor={brandColor}>
      <AppStoreProvider>
        <App />
      </AppStoreProvider>
    </ThemeProvider>
  );
}
