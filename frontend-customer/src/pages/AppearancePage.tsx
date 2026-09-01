import { AppIcon, type IconName } from '../components/AppIcon';
import { useAppTheme, type ThemePreference } from '../theme';

const OPTIONS: Array<{
  value: ThemePreference;
  title: string;
  subtitle: string;
  icon: IconName;
}> = [
  {
    value: 'light',
    title: 'Light',
    subtitle: 'Bright interface with warm food-first accents',
    icon: 'sun',
  },
  {
    value: 'dark',
    title: 'Dark',
    subtitle: 'Low-glare surfaces with richer contrast at night',
    icon: 'moon',
  },
  {
    value: 'system',
    title: 'System',
    subtitle: 'Automatically follows your device appearance',
    icon: 'phone',
  },
];

/** `mobile/src/screens/profile/appearance/AppearanceScreen.tsx`. */
export function AppearancePage() {
  const { theme, preference, systemMode, setPreference } = useAppTheme();
  const resolved = preference === 'system' ? systemMode : preference;

  return (
    <div className="screen">
      <section className="panel">
        <h2 className="panel__heading">Appearance</h2>
        <p className="panel__helper">
          Choose the look you want across the app. Your selection is saved and applies to
          screens, tabs, cards, and sheets.
        </p>

        <div className="active-mode">
          <span className="active-mode__icon">
            <AppIcon name={theme.mode === 'dark' ? 'moon' : 'sun'} size={20} />
          </span>
          <span className="active-mode__copy">
            <strong>Active appearance</strong>
            <small>
              {resolved === 'dark' ? 'Dark' : 'Light'} mode
              {preference === 'system' ? ' via System setting' : ''}
            </small>
          </span>
          <span className="pill pill--brand">Live</span>
        </div>

        <div className="option-list">
          {OPTIONS.map((option) => {
            const active = preference === option.value;
            return (
              <button
                key={option.value}
                aria-pressed={active}
                className={active ? 'option-row option-row--active' : 'option-row'}
                onClick={() => setPreference(option.value)}
                type="button"
              >
                <span className="option-row__icon">
                  <AppIcon name={option.icon} size={19} />
                </span>
                <span className="option-row__copy">
                  <strong>{option.title}</strong>
                  <small>{option.subtitle}</small>
                </span>
                <span className="option-row__check">
                  {active ? <AppIcon name="check" size={15} strokeWidth={2.6} /> : null}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <p className="screen-footnote">
        The accent colour is set by the restaurant, not by this screen — dark mode lifts it
        to stay legible on a dark ground rather than replacing it.
      </p>
    </div>
  );
}
