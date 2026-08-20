import { useCallback, useEffect, useMemo, useState } from 'react';
import { AppShell } from './components/AppShell';
import { CartReplacementModal } from './components/CartReplacementModal';
import { OfferPromptModal } from './components/OfferPromptModal';
import { ToastViewport } from './components/ToastViewport';
import { useAppStore } from './hooks/useAppStore';
import { api, toNumber } from './services/api';
import type { AppliedPersonalizedOffer, ChatSuggestionItem, GeneratedCombo, MenuItem, PersonalizedOfferCard, Restaurant } from './types/app';
import { checkAuthAndRedirect } from './utils/authRedirect';
import { buildMenuItemFromGeneratedComboItem } from './utils/generatedComboCart';
import { isCustomizableMenuItem } from './utils/menuItemCustomization';
import { CartPage } from './pages/CartPage';
import { ChatPage } from './pages/ChatPage';
import { HomePage } from './pages/HomePage';
import { LoginPage } from './pages/LoginPage';
import { FavoritesPage } from './pages/FavoritesPage';
import { OrdersPage } from './pages/OrdersPage';
import { OrderDetailPage } from './pages/OrderDetailPage';
import { PreferencesOnboardingPage } from './pages/PreferencesOnboardingPage';
import { ProfilePage } from './pages/ProfilePage';
import { ProfileDetailsPage } from './pages/ProfileDetailsPage';
import { ProfileHelpPage } from './pages/ProfileHelpPage';
import { ProfileOrdersPage } from './pages/ProfileOrdersPage';
import { ProfileSettingsPage } from './pages/ProfileSettingsPage';
import { RegisterPage } from './pages/RegisterPage';
import { MenuItemDetailPage } from './pages/MenuItemDetail';
import { RestaurantPage } from './pages/RestaurantPage';
import type { UserPreferences } from './types/app';

function usePathname() {
  const [pathname, setPathname] = useState(window.location.pathname);

  const navigate = useCallback((nextPath: string) => {
    setPathname((currentPath) => {
      if (nextPath === currentPath) {
        return currentPath;
      }
      window.history.pushState({}, '', nextPath);
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return nextPath;
    });
  }, []);

  useEffect(() => {
    const handlePopState = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, []);

  return { pathname, navigate };
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
  const { pathname, navigate } = usePathname();
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
  const cartSubtotal = useMemo(
    () => cart.items.reduce((total, item) => total + toNumber(item.menuItem.price) * item.quantity, 0),
    [cart.items],
  );

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
        currentPath={guardedPathname}
        cartCount={cartCount}
        cartSubtotal={cartSubtotal}
        isAuthenticated={isAuthenticated}
        userName={user?.full_name ?? null}
        onNavigate={navigate}
        onOpenCart={handleOpenCart}
      >
        {page}
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
