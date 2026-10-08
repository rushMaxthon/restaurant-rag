import { Linking } from 'react-native';

/**
 * Turn-by-turn in Google Maps, two-wheeler mode when the app is there,
 * otherwise the web directions (which offer to open the app). Coordinates
 * when we have them - an address string can geocode to the wrong lane.
 */
export async function openNavigation(lat: number | null, lng: number | null, address: string): Promise<void> {
  const target = lat != null && lng != null ? `${lat},${lng}` : encodeURIComponent(address);
  const app = `google.navigation:q=${target}&mode=l`;
  try {
    await Linking.openURL(app);
  } catch {
    await Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${target}&travelmode=two-wheeler`);
  }
}

export async function call(phone: string): Promise<boolean> {
  if (!phone) return false;
  try {
    await Linking.openURL(`tel:${phone.replace(/[^\d+]/g, '')}`);
    return true;
  } catch {
    return false;
  }
}
