import React, { useEffect, useState } from 'react';
import { StripeProvider } from '@stripe/stripe-react-native';
import { api } from '@services/api';
import { useSession } from '@hooks/useAppStore';

interface StripeBootstrapProps {
  children: React.ReactElement | React.ReactElement[];
}

/**
 * Supplies the Stripe publishable key to the SDK.
 *
 * The key is fetched from the backend rather than compiled into the bundle, so
 * rotating it — or pointing a build at a different Stripe account — needs no
 * app release. Until it arrives the provider renders with an empty key, which
 * is harmless: nothing opens a payment sheet before checkout.
 */
export function StripeBootstrap({
  children,
}: StripeBootstrapProps): React.JSX.Element {
  const { token, appConfig } = useSession();
  const [publishableKey, setPublishableKey] = useState('');

  useEffect(() => {
    if (!token) {
      setPublishableKey('');
      return;
    }

    let active = true;
    api
      .getPaymentConfig(token)
      .then(config => {
        if (active && config.stripe_enabled) {
          setPublishableKey(config.publishable_key);
        }
      })
      .catch(() => {
        // Card payments simply stay unavailable; COD is unaffected.
      });

    return () => {
      active = false;
    };
  }, [token]);

  return (
    <StripeProvider
      merchantIdentifier={`merchant.${appConfig?.bundle_id ?? 'com.quickbite'}`}
      publishableKey={publishableKey}
    >
      {children}
    </StripeProvider>
  );
}
