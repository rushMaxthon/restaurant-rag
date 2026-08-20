import { useContext } from 'react';
import { AdminStoreContext } from '../store/AdminStoreContext';

export function useAdminStore() {
  const value = useContext(AdminStoreContext);
  if (!value) {
    throw new Error('useAdminStore must be used within AdminStoreProvider');
  }
  return value;
}
