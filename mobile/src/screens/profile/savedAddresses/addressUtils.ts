import type {
  SavedAddress,
  SavedAddressLabel,
  SelectedLocation,
} from '@/types/app';

export const savedAddressLabelCopy: Record<SavedAddressLabel, string> = {
  HOME: 'Home',
  WORK: 'Work',
  OTHER: 'Other',
};

export function mapSavedAddressToSelectedLocation(
  address: SavedAddress,
): SelectedLocation {
  return {
    latitude: null,
    longitude: null,
    address: address.formatted_address,
    city: address.city || address.state || 'Saved address',
    savedAddressId: address.id,
    label: address.label,
    phoneNumber: address.phone_number,
    isDefault: address.is_default,
  };
}

export function buildSavedAddressSubtitle(address: SavedAddress): string {
  return [address.landmark, address.city, address.state]
    .filter(value => Boolean(value && value.trim().length > 0))
    .join(' • ');
}
