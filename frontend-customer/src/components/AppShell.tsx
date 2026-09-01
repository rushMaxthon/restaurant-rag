import type { PropsWithChildren, ReactNode } from 'react';
import { AppIcon, type IconName } from './AppIcon';
import { useAppConfig } from '../store/useAppConfig';

interface AppShellProps extends PropsWithChildren {
  currentPath: string;
  cartCount: number;
  isAuthenticated: boolean;
  userName: string | null;
  locationLabel: string;
  locationSubLabel: string;
  onNavigate: (path: string) => void;
  onBack: () => void;
  onOpenCart: () => void;
}

/** The desktop nav. Same destinations as the tabs, named as a site names them. */
const SITE_LINKS: Array<{ path: string; label: string }> = [
  { path: '/', label: 'Home' },
  { path: '/menu', label: 'Menu' },
  { path: '/orders', label: 'Orders' },
  { path: '/chat', label: 'Ask AI' },
];

const TABS: Array<{ path: string; label: string; icon: IconName }> = [
  { path: '/', label: 'Home', icon: 'home' },
  { path: '/orders', label: 'Orders', icon: 'receipt' },
  { path: '/chat', label: 'Chat', icon: 'chat' },
  { path: '/profile', label: 'Profile', icon: 'person' },
];

/**
 * Titles for the screens that are pushed rather than tabbed.
 *
 * The phone gets these from the navigator's `options.title`; this is the same
 * table. A path that is not listed and is not a tab falls back to no header,
 * which is what the app does for the screens that draw their own.
 */
const STACK_TITLES: Record<string, string> = {
  '/cart': 'Cart',
  '/checkout': 'Checkout',
  '/favorites': 'Favorites',
  '/search': 'Search',
  '/picks': 'Personalized Picks',
  '/menu': 'Full menu',
  '/offers': 'Offers',
  '/profile/details': 'Profile details',
  '/profile/preferences': 'Taste preferences',
  '/profile/orders': 'Order history',
  '/profile/settings': 'Settings',
  '/profile/appearance': 'Appearance',
  '/profile/help': 'Help & support',
};

function stackTitle(path: string): string | null {
  if (STACK_TITLES[path]) {
    return STACK_TITLES[path];
  }
  if (path.startsWith('/orders/')) {
    return 'Order details';
  }
  if (path.startsWith('/menu-item/')) {
    return 'Menu item';
  }
  return null;
}

function isTabActive(currentPath: string, tabPath: string): boolean {
  if (tabPath === '/') {
    return currentPath === '/';
  }
  if (tabPath === '/orders') {
    return currentPath === '/orders' || currentPath.startsWith('/orders/');
  }
  if (tabPath === '/menu') {
    return currentPath === '/menu' || currentPath.startsWith('/menu-item/');
  }
  return currentPath === tabPath || currentPath.startsWith(`${tabPath}/`);
}

function initialOf(name: string | null): string {
  const trimmed = (name ?? '').trim();
  return trimmed ? trimmed.slice(0, 1).toUpperCase() : '';
}

/**
 * The home screen's own header: identity on the left, where you are in the
 * middle, and the three actions on the right. Distinct from the stack header
 * because it is the only screen with nothing to go back to.
 */
function HomeHeader({
  cartCount,
  locationLabel,
  locationSubLabel,
  onNavigate,
  onOpenCart,
  userName,
}: Pick<
  AppShellProps,
  'cartCount' | 'locationLabel' | 'locationSubLabel' | 'onNavigate' | 'onOpenCart' | 'userName'
>) {
  const initial = initialOf(userName);
  return (
    <div className="app-header app-header--home">
      <button
        aria-label="Profile"
        className="app-header__avatar"
        onClick={() => onNavigate('/profile')}
        type="button"
      >
        {initial ? initial : <AppIcon name="person" size={20} />}
      </button>

      <button
        className="app-header__location"
        onClick={() => onNavigate('/profile')}
        type="button"
      >
        <span className="app-header__location-copy">
          <strong>{locationLabel}</strong>
          <small>{locationSubLabel}</small>
        </span>
        <AppIcon name="chevron-down" size={16} />
      </button>

      <div className="app-header__actions">
        <button
          aria-label="Favorites"
          className="app-header__icon-button"
          onClick={() => onNavigate('/favorites')}
          type="button"
        >
          <AppIcon name="heart" size={19} />
        </button>
        <button aria-label="Cart" className="app-header__icon-button" onClick={onOpenCart} type="button">
          <AppIcon name="bag" size={19} />
          {cartCount > 0 ? (
            <span className="app-header__badge">{cartCount > 9 ? '9+' : cartCount}</span>
          ) : null}
        </button>
      </div>
    </div>
  );
}

/** The pushed-screen header: back, centred title, optional trailing action. */
function StackHeader({
  onBack,
  title,
  right,
}: {
  onBack: () => void;
  title: string;
  right?: ReactNode;
}) {
  return (
    <div className="app-header">
      <div className="app-header__side">
        <button aria-label="Go back" className="app-header__back" onClick={onBack} type="button">
          <AppIcon name="arrow-back" size={20} />
        </button>
      </div>
      <div className="app-header__title">{title}</div>
      <div className="app-header__side app-header__side--right">{right}</div>
    </div>
  );
}

export function AppShell({
  children,
  currentPath,
  cartCount,
  isAuthenticated,
  userName,
  locationLabel,
  locationSubLabel,
  onNavigate,
  onBack,
  onOpenCart,
}: AppShellProps) {
  const { displayName } = useAppConfig();
  const isHome = currentPath === '/';
  const title = stackTitle(currentPath);
  const isTabScreen = TABS.some((tab) => isTabActive(currentPath, tab.path));
  const isAuthScreen = currentPath.startsWith('/auth/') || currentPath.startsWith('/preferences/');
  const isHomeScreen = !isAuthScreen && (currentPath === '/' || currentPath === '');

  return (
    <div className="app-viewport">
      {/* The desktop chrome. One component renders both: below the site
          breakpoint this is hidden and the phone header and tab bar below take
          over, so the same screens are an app on a handset and a website on a
          desktop without either being a scaled-down version of the other. */}
      {isAuthScreen ? null : (
        <header className="site-header">
          <div className="site-header__inner">
            <button className="site-brand" onClick={() => onNavigate('/')} type="button">
              <span className="site-brand__mark">{displayName.slice(0, 2).toUpperCase()}</span>
              <span className="site-brand__copy">
                <strong>{displayName}</strong>
                <small>{locationSubLabel}</small>
              </span>
            </button>

            <nav aria-label="Sections" className="site-nav">
              {SITE_LINKS.map((link) => (
                <button
                  key={link.path}
                  aria-current={isTabActive(currentPath, link.path) ? 'page' : undefined}
                  className={
                    isTabActive(currentPath, link.path)
                      ? 'site-nav__link site-nav__link--active'
                      : 'site-nav__link'
                  }
                  onClick={() => onNavigate(link.path)}
                  type="button"
                >
                  {link.label}
                </button>
              ))}
            </nav>

            <div className="site-header__actions">
              <button
                aria-label="Search the menu"
                className="site-icon-button"
                onClick={() => onNavigate('/search')}
                type="button"
              >
                <AppIcon name="search" size={19} />
              </button>
              <button
                aria-label="Favorites"
                className="site-icon-button"
                onClick={() => onNavigate('/favorites')}
                type="button"
              >
                <AppIcon name="heart" size={19} />
              </button>
              <button className="site-cart" onClick={onOpenCart} type="button">
                <AppIcon name="bag" size={18} />
                Cart
                {cartCount > 0 ? <span className="site-cart__count">{cartCount}</span> : null}
              </button>
              {isAuthenticated ? (
                <button
                  className="site-account"
                  onClick={() => onNavigate('/profile')}
                  type="button"
                >
                  <span className="site-account__avatar">{initialOf(userName) || 'C'}</span>
                  <span>{(userName ?? 'Account').split(' ')[0]}</span>
                </button>
              ) : (
                <button
                  className="btn btn--sm"
                  onClick={() => onNavigate('/auth/login')}
                  type="button"
                >
                  Log in
                </button>
              )}
            </div>
          </div>
        </header>
      )}

      <div className="app-frame">
        {isAuthScreen ? null : isHome ? (
          <HomeHeader
            cartCount={cartCount}
            locationLabel={locationLabel}
            locationSubLabel={locationSubLabel}
            onNavigate={onNavigate}
            onOpenCart={onOpenCart}
            userName={userName}
          />
        ) : title ? (
          <StackHeader
            onBack={onBack}
            right={
              currentPath === '/cart' || currentPath === '/checkout' ? null : (
                <button
                  aria-label="Cart"
                  className="app-header__icon-button app-header__icon-button--plain"
                  onClick={onOpenCart}
                  type="button"
                >
                  <AppIcon name="bag" size={19} />
                  {cartCount > 0 ? (
                    <span className="app-header__badge">{cartCount > 9 ? '9+' : cartCount}</span>
                  ) : null}
                </button>
              )
            }
            title={title}
          />
        ) : null}

        <main className="app-content">{children}</main>

        {isAuthScreen ? null : (
          <nav aria-label="Primary" className="tab-bar">
            {TABS.map((tab) => {
              const active = isTabActive(currentPath, tab.path);
              return (
                <button
                  key={tab.path}
                  aria-current={active ? 'page' : undefined}
                  className={active ? 'tab-bar__item tab-bar__item--active' : 'tab-bar__item'}
                  onClick={() => onNavigate(tab.path)}
                  type="button"
                >
                  <span className="tab-bar__icon">
                    <AppIcon filled={active} name={tab.icon} size={23} />
                    {tab.path === '/orders' && cartCount > 0 && !isTabScreen ? null : null}
                  </span>
                  <span className="tab-bar__label">{tab.label}</span>
                </button>
              );
            })}
          </nav>
        )}
      </div>

      {!isAuthenticated && !isAuthScreen ? (
        <button className="app-login-cue" onClick={() => onNavigate('/auth/login')} type="button">
          Log in
        </button>
      ) : null}

      {/* Home only. The footer repeats navigation the header already carries,
          and on a screen the customer is working through — a menu, a cart, a
          dish — it is a second set of exits under the thing they came to do. */}
      {isHomeScreen ? (
        <footer className="site-footer">
          <div className="site-footer__inner">
            <div className="site-footer__brand">
              <span className="site-brand__mark">{displayName.slice(0, 2).toUpperCase()}</span>
              <p>
                <strong>{displayName}</strong>
                <span>Order online for delivery or pickup.</span>
              </p>
            </div>
            <nav aria-label="Footer">
              {SITE_LINKS.map((link) => (
                <button key={link.path} onClick={() => onNavigate(link.path)} type="button">
                  {link.label}
                </button>
              ))}
              <button onClick={() => onNavigate('/profile/help')} type="button">
                Help
              </button>
            </nav>
            <small>© {new Date().getFullYear()} {displayName}. All rights reserved.</small>
          </div>
        </footer>
      ) : null}
    </div>
  );
}
