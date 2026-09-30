/**
 * Who is signed in on this screen.
 *
 * Simpler than the customer app's equivalent on purpose: there is no guest
 * state, no per-app identity and nothing to do while signed out except sign
 * in. The session is read from localStorage once, synchronously, because a
 * board that flashes its login screen every time the tablet wakes is a board
 * somebody will sign out of by accident.
 *
 * The context and the `useAuth` hook live in `auth-context.ts`; see the note
 * there for why they are not in this file.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { clearSession, login as apiLogin, onSessionExpired, readSession, storeSession } from './api'
import { AuthContext, type AuthValue } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  // Read once at mount rather than in an effect: there is no server render to
  // disagree with, so the correct screen can be the first one painted.
  const [session, setSession] = useState(() => readSession())
  const [expired, setExpired] = useState(false)

  // Because the session is read only once, a 401 has to be pushed in here —
  // otherwise the board keeps rendering for a token the server has refused.
  useEffect(
    () =>
      onSessionExpired(() => {
        setSession(null)
        setExpired(true)
      }),
    [],
  )

  const signIn = useCallback(async (email: string, password: string) => {
    const next = await apiLogin(email, password)
    storeSession(next)
    setSession(next)
    setExpired(false)
  }, [])

  const signOut = useCallback(() => {
    clearSession()
    setSession(null)
    setExpired(false)
  }, [])

  const value = useMemo<AuthValue>(
    () => ({ session, expired, signIn, signOut }),
    [session, expired, signIn, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
