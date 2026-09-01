import { AppIcon, type IconName } from '../AppIcon';
import { useAppStore } from '../../hooks/useAppStore';
import { useAppConfig } from '../../store/useAppConfig';

interface SignedOutGateProps {
  icon: IconName;
  title: string;
  text: string;
  /** Three concrete things this screen gives you once signed in. */
  points: string[];
  onNavigate: (path: string) => void;
  /** Where to return after signing in. */
  redirectPath: string;
}

/**
 * What Orders, Chat and Favorites show before anyone has logged in.
 *
 * Each screen previously rendered a bare card in the middle of an otherwise
 * empty page — three different shapes, all of them reading as a page that had
 * failed to load rather than one asking you to sign in. This is one composition
 * with room to say what the screen is for, both ways in, and a way to keep
 * browsing for someone not ready to hand over an email.
 */
export function SignedOutGate({
  icon,
  title,
  text,
  points,
  onNavigate,
  redirectPath,
}: SignedOutGateProps) {
  const { displayName } = useAppConfig();
  const { setPendingAuthRedirectPath } = useAppStore();

  return (
    <div className="screen screen--centred">
      <section className="gate">
        <span aria-hidden="true" className="gate__glow gate__glow--one" />
        <span aria-hidden="true" className="gate__glow gate__glow--two" />

        <div className="gate__copy">
          <span className="gate__icon">
            <AppIcon name={icon} size={26} />
          </span>
          <h1 className="gate__title">{title}</h1>
          <p className="gate__text">{text}</p>

          <div className="gate__actions">
            <button
              className="btn"
              onClick={() => {
                // The store's own mechanism, so signing in returns to the
                // screen that asked rather than dropping you on Home.
                setPendingAuthRedirectPath(redirectPath);
                onNavigate('/auth/login');
              }}
              type="button"
            >
              Log in
            </button>
            <button
              className="btn btn--quiet"
              onClick={() => {
                setPendingAuthRedirectPath(redirectPath);
                onNavigate('/auth/register');
              }}
              type="button"
            >
              Create an account
            </button>
          </div>

          <button className="gate__browse" onClick={() => onNavigate('/menu')} type="button">
            Or browse the {displayName} menu
            <AppIcon name="chevron-right" size={15} />
          </button>
        </div>

        <ul className="gate__points">
          {points.map((point) => (
            <li key={point}>
              <span className="gate__tick">
                <AppIcon name="check" size={13} strokeWidth={2.8} />
              </span>
              {point}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
