import { useContext } from 'react';
import { AppConfigContext, type AppConfigValue } from './AppConfigContext';

/** Split from the provider so the provider file keeps fast refresh. */
export function useAppConfig(): AppConfigValue {
  return useContext(AppConfigContext);
}
