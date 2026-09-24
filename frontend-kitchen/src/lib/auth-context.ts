/**
 * The auth context and its hook, kept apart from the provider that fills it.
 *
 * Split purely so each module has one kind of export. React Fast Refresh can
 * only preserve state across an edit when a file exports components and
 * nothing else — a file mixing a provider with a hook gets remounted on every
 * save, which in this app means being signed out while working on it.
 */

import { createContext, useContext } from 'react'

import type { KitchenSession } from './api'

export type AuthValue = {
  session: KitchenSession | null
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth used outside AuthProvider')
  return value
}
