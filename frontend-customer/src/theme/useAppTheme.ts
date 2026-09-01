import { useContext } from 'react';
import { ThemeContext, type ThemeContextValue } from './ThemeContext';

/**
 * Lives beside the provider rather than inside it, matching how the app store
 * is split: a file that exports both a component and a hook loses fast refresh.
 */
export function useAppTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
