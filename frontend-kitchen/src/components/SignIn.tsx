import { AlertTriangle, ChefHat, Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { unlock } from '../lib/sound'

/**
 * The only screen there is when signed out.
 *
 * The submit handler is also where audio is unlocked, because a browser will
 * not play a sound until the page has had a real user gesture — and this is
 * the only one guaranteed to happen before the first ticket arrives.
 */
export function SignIn() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    // Before the await: the gesture that permits audio is this submit, and
    // Safari will not honour it once the call stack has gone async.
    unlock()
    try {
      await signIn(email.trim(), password)
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Could not sign in. Check the connection and try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="kds-signin">
      <form className="kds-signin__card" onSubmit={handleSubmit}>
        <span className="kds-signin__mark">
          <ChefHat size={26} strokeWidth={2.3} />
        </span>
        <h1>Kitchen board</h1>
        <p className="kds-signin__sub">
          Sign in with the account your manager set up for this screen.
        </p>

        {error ? (
          <p className="kds-alert" role="alert">
            <AlertTriangle size={14} />
            <span>{error}</span>
          </p>
        ) : null}

        <label className="kds-field">
          <span>Email</span>
          <input
            autoComplete="username"
            autoFocus
            className="kds-input"
            disabled={busy}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="kitchen@restaurant.com"
            required
            type="email"
            value={email}
          />
        </label>

        <label className="kds-field">
          <span>Password</span>
          <input
            autoComplete="current-password"
            className="kds-input"
            disabled={busy}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••"
            required
            type="password"
            value={password}
          />
        </label>

        <button className="kds-btn" disabled={busy} type="submit">
          {busy ? <Loader2 className="kds-spin" size={16} /> : null}
          {busy ? 'Signing in…' : 'Open the board'}
        </button>

        <p className="kds-signin__foot">
          This board shows only the orders for the branch this account is
          assigned to. Ask your manager if you need a different one.
        </p>
      </form>
    </div>
  )
}
