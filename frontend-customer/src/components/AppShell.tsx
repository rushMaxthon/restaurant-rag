import type { PropsWithChildren } from 'react';
import { formatCurrency } from '../services/api';

interface AppShellProps extends PropsWithChildren {
  currentPath: string;
  cartCount: number;
  cartSubtotal: number;
  isAuthenticated: boolean;
  userName: string | null;
  onNavigate: (path: string) => void;
  onOpenCart: () => void;
}

export function AppShell({
  children,
  currentPath,
  cartCount,
  cartSubtotal,
  isAuthenticated,
  userName,
  onNavigate,
  onOpenCart,
}: AppShellProps) {
  const navItems = [
    { path: '/', label: 'Home' },
    { path: '/favorites', label: 'Favorites' },
    { path: '/chat', label: 'AI Chat' },
    { path: '/profile', label: 'Profile' },
  ];

  const isNavItemActive = (path: string) => {
    if (path === '/') {
      return currentPath === '/';
    }

    return currentPath === path || currentPath.startsWith(`${path}/`);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => onNavigate('/')} type="button">
          <span className="brand__mark">RR</span>
          <span>
            <strong>Restaurant RAG</strong>
            <small>Smarter cravings, faster checkout</small>
          </span>
        </button>
        <nav className="topbar__nav">
          {navItems.map((item) => (
            <button
              key={item.path}
              className={isNavItemActive(item.path) ? 'nav-link nav-link--active' : 'nav-link'}
              onClick={() => onNavigate(item.path)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="topbar__actions">
          <button className="cart-summary" onClick={onOpenCart} type="button">
            <span>Cart {cartCount > 0 ? `· ${cartCount}` : ''}</span>
            <strong>{formatCurrency(cartSubtotal)}</strong>
          </button>
          {isAuthenticated ? (
            <button className="account-pill account-pill--single" onClick={() => onNavigate('/profile')} type="button">
              <span className="account-pill__avatar">{(userName ?? 'C').slice(0, 1).toUpperCase()}</span>
              <span>{userName ?? 'Customer'}</span>
            </button>
          ) : (
            <button className="primary-button primary-button--small" onClick={() => onNavigate('/auth/login')} type="button">
              Login
            </button>
          )}
        </div>
      </header>
      <main className="page-frame">{children}</main>
      <nav className="mobile-nav">
        {navItems.map((item) => (
          <button
            key={item.path}
            className={isNavItemActive(item.path) ? 'mobile-nav__item mobile-nav__item--active' : 'mobile-nav__item'}
            onClick={() => onNavigate(item.path)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>
      {cartCount > 0 ? (
        <button className="mobile-cart-fab" onClick={onOpenCart} type="button">
          <span>{cartCount}</span>
          <strong>{formatCurrency(cartSubtotal)}</strong>
        </button>
      ) : null}
    </div>
  );
}
