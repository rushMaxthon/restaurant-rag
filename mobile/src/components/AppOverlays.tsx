import React from 'react';
import { CartReplacementModal } from '@components/CartReplacementModal';
import { ToastHost } from '@components/ToastHost';
import { useAppActions, usePrompts, useToasts } from '@hooks/useAppStore';

/**
 * Renders the app-wide toast stack and the cart replacement prompt.
 *
 * These live beside the navigator rather than inside it: toasts arrive
 * constantly, and subscribing the navigator to them re-created every
 * `Stack.Screen` element on each one. Isolating them here means a toast
 * re-renders only this component.
 */
export const AppOverlays = React.memo(function AppOverlays() {
  const toasts = useToasts();
  const { pendingCartReplacement } = usePrompts();
  const { dismissToast, dismissCartReplacement, confirmCartReplacement } =
    useAppActions();

  return (
    <>
      <CartReplacementModal
        onCancel={dismissCartReplacement}
        onConfirm={confirmCartReplacement}
        visible={Boolean(pendingCartReplacement)}
      />
      <ToastHost onDismiss={dismissToast} toasts={toasts} />
    </>
  );
});
