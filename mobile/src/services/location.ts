import { NativeModules, PermissionsAndroid, Platform } from 'react-native';
import { mockLocations, type LocationSearchResult } from '@/data/mockLocations';
import type { SelectedLocation } from '@/types/app';

const SEARCH_DELAY_MS = 280;

interface GeolocationModule {
  requestAuthorization: (mode: 'whenInUse' | 'always') => Promise<string>;
  getCurrentPosition: (
    success: (position: {
      coords: { latitude: number; longitude: number };
    }) => void,
    error: (error: { message?: string }) => void,
    options: {
      enableHighAccuracy: boolean;
      timeout: number;
      maximumAge: number;
      forceRequestLocation: boolean;
      showLocationDialog: boolean;
    },
  ) => void;
}

function wait(ms: number) {
  return new Promise<void>(resolve => {
    setTimeout(resolve, ms);
  });
}

function getGeolocationModule(): GeolocationModule {
  if (!NativeModules.RNFusedLocation) {
    throw new Error(
      Platform.OS === 'ios'
        ? 'Location services are not linked yet. Run `npm run install`, then rebuild the iOS app.'
        : 'Location services are not linked yet. Rebuild the Android app after installing native dependencies.',
    );
  }

  // Delay module loading until we know the native side exists.
  return require('react-native-geolocation-service')
    .default as GeolocationModule;
}

async function ensureLocationPermission(): Promise<void> {
  if (Platform.OS === 'ios') {
    const geolocation = getGeolocationModule();
    const status = await geolocation.requestAuthorization('whenInUse');
    if (status !== 'granted') {
      throw new Error(
        'Location permission is required to use your current location.',
      );
    }
    return;
  }

  const granted = await PermissionsAndroid.request(
    PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
    {
      title: 'Use your current location',
      message:
        'Restaurant RAG uses your location to suggest nearby restaurants and delivery areas.',
      buttonPositive: 'Allow',
      buttonNegative: 'Not now',
    },
  );

  if (granted !== PermissionsAndroid.RESULTS.GRANTED) {
    throw new Error(
      'Location permission was denied. You can still search manually.',
    );
  }
}

async function reverseGeocode(
  latitude: number,
  longitude: number,
): Promise<SelectedLocation> {
  try {
    const response = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${encodeURIComponent(
        latitude,
      )}&lon=${encodeURIComponent(longitude)}`,
      {
        headers: {
          Accept: 'application/json',
        },
      },
    );

    if (response.ok) {
      const payload = (await response.json()) as {
        display_name?: string;
        address?: {
          city?: string;
          town?: string;
          village?: string;
          suburb?: string;
          state_district?: string;
          state?: string;
        };
      };
      const city =
        payload.address?.city ??
        payload.address?.town ??
        payload.address?.village ??
        payload.address?.suburb ??
        payload.address?.state_district ??
        payload.address?.state ??
        'Current location';

      return {
        latitude,
        longitude,
        address: payload.display_name ?? `${city}`,
        city,
      };
    }
  } catch {
    // Fall back to a friendly label below.
  }

  return {
    latitude,
    longitude,
    address: `Current location (${latitude.toFixed(4)}, ${longitude.toFixed(
      4,
    )})`,
    city: 'Current location',
  };
}

export const locationService = {
  async searchLocations(query: string): Promise<LocationSearchResult[]> {
    await wait(SEARCH_DELAY_MS);

    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return mockLocations.slice(0, 6);
    }

    return mockLocations
      .filter(location =>
        [location.title, location.subtitle, location.address, location.city]
          .join(' ')
          .toLowerCase()
          .includes(normalized),
      )
      .slice(0, 10);
  },

  async getCurrentLocation(): Promise<SelectedLocation> {
    await ensureLocationPermission();
    const geolocation = getGeolocationModule();

    const coords = await new Promise<{ latitude: number; longitude: number }>(
      (resolve, reject) => {
        geolocation.getCurrentPosition(
          position => {
            resolve({
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
            });
          },
          error => {
            reject(
              new Error(
                error.message ||
                  'Unable to fetch your current location right now.',
              ),
            );
          },
          {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 15000,
            forceRequestLocation: true,
            showLocationDialog: true,
          },
        );
      },
    );

    return reverseGeocode(coords.latitude, coords.longitude);
  },
};
