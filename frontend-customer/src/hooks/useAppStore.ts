import { useContext } from 'react';
import { AppStoreContext } from '../store/AppStoreContext';

export function useAppStore() {
  const value = useContext(AppStoreContext);
  if (!value) {
    throw new Error('useAppStore must be used inside AppStoreProvider');
  }

  return value;
}
