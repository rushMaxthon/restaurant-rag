import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import { AppShell } from './components/AppShell';
import { CartReplacementModal } from './components/CartReplacementModal';
import { OfferPromptModal } from './components/OfferPromptModal';
import { ToastViewport } from './components/ToastViewport';
import { useAppStore } from './hooks/useAppStore';
import { useAppConfig } from './store/useAppConfig';
import { api } from './services/api';
import type { AppliedPersonalizedOffer, ChatSuggestionItem, GeneratedCombo, MenuItem, PersonalizedOfferCard, Restaurant } from './types/app';
import { checkAuthAndRedirect } from './utils/authRedirect';
import { buildMenuItemFromGeneratedComboItem } from './utils/generatedComboCart';
import { isCustomizableMenuItem } from './utils/menuItemCustomization';
import { HomePage } from './pages/HomePage';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import type { UserPreferences } from './types/app';


// Routes a first visit does not render are fetched when they are opened.
const CartPage = lazy(() => import('./pages/CartPage').then((m) => ({ default: m.CartPage })));
const ChatPage = lazy(() => import('./pages/ChatPage').then((m) => ({ default: m.ChatPage })));
const FavoritesPage = lazy(() => import('./pages/FavoritesPage').then((m) => ({ default: m.FavoritesPage })));
const OrdersPage = lazy(() => import('./pages/OrdersPage').then((m) => ({ default: m.OrdersPage })));
const OrderDetailPage = lazy(() => import('./pages/OrderDetailPage').then((m) => ({ default: m.OrderDetailPage })));
const PreferencesOnboardingPage = lazy(() => import('./pages/PreferencesOnboardingPage').then((m) => ({ default: m.PreferencesOnboardingPage })));
const ProfilePage = lazy(() => import('./pages/ProfilePage').then((m) => ({ default: m.ProfilePage })));
const ProfileDetailsPage = lazy(() => import('./pages/ProfileDetailsPage').then((m) => ({ default: m.ProfileDetailsPage })));
const ProfileHelpPage = lazy(() => import('./pages/ProfileHelpPage').then((m) => ({ default: m.ProfileHelpPage })));
const ProfileOrdersPage = lazy(() => import('./pages/ProfileOrdersPage').then((m) => ({ default: m.ProfileOrdersPage })));
const ProfileSettingsPage = lazy(() => import('./pages/ProfileSettingsPage').then((m) => ({ default: m.ProfileSettingsPage })));
const MenuItemDetailPage = lazy(() => import('./pages/MenuItemDetail').then((m) => ({ default: m.MenuItemDetailPage })));
const RestaurantPage = lazy(() => import('./pages/RestaurantPage').then((m) => ({ default: m.RestaurantPage })));
const AppearancePage = lazy(() => import('./pages/AppearancePage').then((m) => ({ default: m.AppearancePage })));
const SearchPage = lazy(() => import('./pages/SearchPage').then((m) => ({ default: m.SearchPage })));

function usePathname() {
  const [pathname, setPathname] = useState(window.location.pathname);

  /**
   * Push one entry and move.
   *
   * The push and the scroll happen here rather than inside the `setPathname`
   * updater. A state updater has to be a pure function of the previous state:
   * React invokes it twice under StrictMode to prove that it is, which pushed
   * two history entries per navigation and made the back button need two
   * presses to go one screen back.
   *
   * `window.location.pathname` is the current path rather than the `pathname`
   * state for the same reason the effect below reads it — the URL is what the
   * history stack actually holds, and reading it keeps this callback stable
   * instead of rebuilding on every navigation.
   */
  const navigate = useCallback((nextPath: string) => {
    if (nextPath === window.location.pathname) {
      return;
    }
    window.history.pushState({}, '', nextPath);
    window.scrollTo({ top: 0, behavior: 'smooth' });
    setPathname(nextPath);
  }, []);

  /**
   * Pop the stack, the way the phone's back arrow does.
   *
   * Falls through to Home when there is nothing to pop — a deep link opened in
   * a fresh tab has no history entry behind it, and a back button that does
   * nothing reads as broken.
   */
  const back = useCallback(() => {
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    window.history.pushState({}, '', '/');
    setPathname('/');
  }, []);

  useEffect(() => {
    const handlePopState = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, []);

  return { pathname, navigate, back };
}

function matchRestaurantPath(pathname: string): string | null {
  const match = pathname.match(/^\/restaurant\/([^/]+)$/);
  return match?.[1] ?? null;
}

function matchMenuItemPath(pathname: string): string | null {
  const match = pathname.match(/^\/menu-item\/([^/]+)$/);
  return match?.[1] ?? null;
}

function matchOrderPath(pathname: string): string | null {
  const match = pathname.match(/^\/orders\/([^/]+)$/);
  return match?.[1] ?? null;
}

function App() {
  const {
    token,
    user,
    cart,
    chatSessionId,
    pendingCartReplacement,
    pendingOfferPrompt,
    toasts,
    isAuthenticated,
    applyPendingOfferPrompt,
    confirmCartReplacement,
    continuePendingOfferPrompt,
    dismissPendingOfferPrompt,
    dismissCartReplacement,
    logout,
    preferences,
    preferencesOnboardingCompleted,
    setChatSessionId,
    setPendingAuthRedirectPath,
    setSelectedPersonalizedOffer,
    addToCart,
    requestAddToCart,
    dismissToast,
    pushToast,
  } = useAppStore();
  const appConfig = useAppConfig();
  const { pathname, navigate, back } = usePathname();
  const onboardingAllowedPaths = useMemo(
    () => new Set(['/preferences/onboarding', '/auth/login', '/auth/register']),
    [],
  );
  const guardedPathname =
    !preferencesOnboardingCompleted && !onboardingAllowedPaths.has(pathname)
      ? '/preferences/onboarding'
      : pathname;

  useEffect(() => {
    if (!user) {
      return;
    }

    if (user.role !== 'CUSTOMER') {
      logout();
      pushToast(
        'Access blocked',
        'Admin/Owner accounts cannot access the customer app.',
        'error',
      );
      navigate('/auth/login');
    }
  }, [logout, navigate, pushToast, user]);

  useEffect(() => {
    if (!preferencesOnboardingCompleted && !onboardingAllowedPaths.has(pathname)) {
      navigate('/preferences/onboarding');
      return;
    }

    if (preferencesOnboardingCompleted && pathname === '/preferences/onboarding') {
      navigate('/');
    }
  }, [navigate, onboardingAllowedPaths, pathname, preferencesOnboardingCompleted]);

  const cartCount = useMemo(
    () => cart.items.reduce((total, item) => total + item.quantity, 0),
    [cart.items],
  );
  // What the header's location control reads. On the phone this is the branch
  // the customer picked; here it is the branch the cart is already tied to,
  // falling back to the app's own restaurant before anything is in the cart.
  const locationLabel = appConfig.displayName;
  const locationSubLabel =
    cart.restaurantLocationName ?? 'Choose delivery or pickup at checkout';


  const requireAuth = useCallback((redirectPath: string) =>
    checkAuthAndRedirect({
      isAuthenticated,
      redirectPath,
      onNavigate: navigate,
      pushToast,
      setPendingAuthRedirectPath,
    }), [isAuthenticated, navigate, pushToast, setPendingAuthRedirectPath]);

  const handleAddMenuItem = useCallback((item: MenuItem, restaurant: Restaurant) => {
    if (!requireAuth(pathname)) {
      return;
    }

    if (isCustomizableMenuItem(item)) {
      navigate(`/menu-item/${item.id}`);
      return;
    }

    void requestAddToCart({
      menuItem: item,
      restaurantId: restaurant.id,
      restaurantName: restaurant.name,
    });
  }, [navigate, pathname, requestAddToCart, requireAuth]);

  const handleOpenCart = useCallback(() => {
    if (!requireAuth('/cart')) {
      return;
    }

    navigate('/cart');
  }, [navigate, requireAuth]);

  const handleAddSuggestion = useCallback((item: ChatSuggestionItem) => {
    navigate(`/menu-item/${item.id}`);
  }, [navigate]);

  const handleAddChatCombo = useCallback((combo: GeneratedCombo) => {
    for (const item of combo.items) {
      addToCart({
        menuItem: buildMenuItemFromGeneratedComboItem(item, {
          source: 'home-generated-combo',
          restaurantId: combo.restaurant_id,
          restaurantLocationId: combo.restaurant_location_id,
          restaurantLocationName: combo.restaurant_location_name,
          restaurantCuisineType: null,
          createdAt: combo.created_at,
          updatedAt: combo.updated_at,
        }),
        restaurantId: combo.restaurant_id,
        restaurantName: combo.restaurant_name,
        restaurantLocationId: combo.restaurant_location_id,
        restaurantLocationName: combo.restaurant_location_name,
        quantity: item.quantity,
        silent: true,
      });
    }
    pushToast('Combo added', `${combo.combo_name} was added to your cart.`, 'success');
  }, [addToCart, pushToast]);

  const handleOpenChatOffer = useCallback((offer: PersonalizedOfferCard) => {
    const selectedOffer: AppliedPersonalizedOffer = {
      generatedOfferId: offer.generated_offer_id,
      generatedOfferUserMatchId: offer.generated_offer_user_match_id,
      offerId: offer.offer_id,
      offerName: offer.offer_name,
      offerType: offer.offer_type,
      audienceType: offer.audience_type,
      targetType: offer.target_type,
      restaurantId: offer.restaurant_id,
      restaurantName: offer.restaurant_name,
      restaurantLocationId: offer.restaurant_location_id,
      restaurantLocationName: offer.restaurant_location_name,
      offerRestaurantLocationId: offer.offer_restaurant_location_id,
      menuItemId: offer.menu_item_id,
      generatedComboId: offer.generated_combo_id,
      cuisineType: offer.cuisine_type,
      title: offer.title,
      ctaLabel: offer.cta_label,
      discountType: offer.discount_type,
      discountValue: offer.discount_value,
      discountLabel: offer.discount_label,
      maxDiscountAmount: offer.max_discount_amount,
      minimumOrderAmount: offer.minimum_order_amount,
      termsLabel: offer.terms_label,
      expiresAt: offer.expires_at,
    };

    setSelectedPersonalizedOffer(selectedOffer);
    if (token) {
      void api.trackPersonalizedOfferEvents(token, [
        {
          offer_id: offer.offer_id,
          generated_offer_id: offer.generated_offer_id,
          generated_offer_user_match_id: offer.generated_offer_user_match_id,
          event_type: 'CLICKED',
          target_type: offer.target_type,
          target_id:
            offer.menu_item_id
            ?? offer.generated_combo_id
            ?? offer.restaurant_location_id
            ?? offer.restaurant_id,
        },
      ]).catch(() => undefined);
    }

    if (offer.target_type === 'ITEM' && offer.menu_item_id) {
      navigate(`/menu-item/${offer.menu_item_id}`);
      return;
    }
    navigate(`/restaurant/${offer.restaurant_id}`);
  }, [navigate, setSelectedPersonalizedOffer, token]);

  const handleHomeToast = pushToast;
  const homePreferences: UserPreferences | null = preferences;

  const page = (() => {
    const restaurantId = matchRestaurantPath(guardedPathname);
    if (restaurantId) {
      return (
        <RestaurantPage
          restaurantId={restaurantId}
          token={token}
          onNavigate={navigate}
            onAddToCart={handleAddMenuItem}
        />
      );
    }

    const menuItemId = matchMenuItemPath(guardedPathname);
    if (menuItemId) {
      return <MenuItemDetailPage itemId={menuItemId} onNavigate={navigate} token={token} />;
    }

    const orderId = matchOrderPath(guardedPathname);
    if (orderId) {
      return <OrderDetailPage orderId={orderId} onNavigate={navigate} token={token} onToast={pushToast} />;
    }

    switch (guardedPathname) {
      case '/':
        return (
          <HomePage
            addToCart={requestAddToCart}
            onNavigate={navigate}
            onToast={handleHomeToast}
            preferences={homePreferences}
            token={token}
          />
        );
      case '/chat':
        return (
          <ChatPage
            token={token}
            sessionId={chatSessionId}
            onSessionChange={setChatSessionId}
            onNavigate={navigate}
            onAddComboToCart={handleAddChatCombo}
            onOpenOfferFromChat={handleOpenChatOffer}
            onAddSuggestionToCart={handleAddSuggestion}
            onToast={pushToast}
          />
        );
      case '/menu':
        // The branded app's "full menu" is the restaurant screen, pointed at
        // the one restaurant this build is. Keeping it on the same component
        // means the marketplace route and this one cannot drift apart.
        return appConfig.restaurantId ? (
          <RestaurantPage
            onAddToCart={handleAddMenuItem}
            onNavigate={navigate}
            restaurantId={appConfig.restaurantId}
            token={token}
          />
        ) : (
          <HomePage
            addToCart={requestAddToCart}
            onNavigate={navigate}
            onToast={handleHomeToast}
            preferences={homePreferences}
            token={token}
          />
        );
      case '/search':
        return <SearchPage onNavigate={navigate} onToast={pushToast} token={token} />;
      case '/profile/appearance':
        return <AppearancePage />;
      case '/favorites':
        return <FavoritesPage token={token} onNavigate={navigate} onToast={pushToast} />;
      case '/cart':
        return <CartPage onNavigate={navigate} />;
      case '/orders':
        return <OrdersPage token={token} onNavigate={navigate} onToast={pushToast} />;
      case '/preferences/onboarding':
        return <PreferencesOnboardingPage mode="onboarding" onNavigate={navigate} />;
      case '/profile':
        return <ProfilePage token={token} onNavigate={navigate} onToast={pushToast} />;
      case '/profile/preferences':
        return <PreferencesOnboardingPage mode="edit" onNavigate={navigate} />;
      case '/profile/details':
        return <ProfileDetailsPage token={token} onNavigate={navigate} onToast={pushToast} />;
      case '/profile/orders':
        return <ProfileOrdersPage token={token} onNavigate={navigate} onToast={pushToast} />;
      case '/profile/settings':
        return <ProfileSettingsPage token={token} onNavigate={navigate} onToast={pushToast} />;
      case '/profile/help':
        return <ProfileHelpPage token={token} onNavigate={navigate} />;
      case '/auth/login':
        return <LoginPage onNavigate={navigate} />;
      case '/auth/register':
        return <RegisterPage onNavigate={navigate} />;
      default:
        return (
          <HomePage
            addToCart={requestAddToCart}
            onNavigate={navigate}
            onToast={handleHomeToast}
            preferences={homePreferences}
            token={token}
          />
        );
    }
  })();

  return (
    <>
      <AppShell
        cartCount={cartCount}
        currentPath={guardedPathname}
        isAuthenticated={isAuthenticated}
        locationLabel={locationLabel}
        locationSubLabel={locationSubLabel}
        onBack={back}
        onNavigate={navigate}
        onOpenCart={handleOpenCart}
        userName={user?.full_name ?? null}
      >
        {/* One boundary for every lazy route. The fallback is a plain block
            rather than a spinner: the shell around it is already painted, so a
            spinner would flash for the few milliseconds a chunk takes. */}
        <Suspense fallback={<div className="route-fallback" />}>{page}</Suspense>
      </AppShell>
      <CartReplacementModal
        onCancel={dismissCartReplacement}
        onConfirm={confirmCartReplacement}
        visible={Boolean(pendingCartReplacement)}
      />
      <OfferPromptModal
        onApply={applyPendingOfferPrompt}
        onContinue={continuePendingOfferPrompt}
        onDismiss={dismissPendingOfferPrompt}
        prompt={pendingOfferPrompt}
        visible={Boolean(pendingOfferPrompt)}
      />
      <ToastViewport toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}

export default App;
