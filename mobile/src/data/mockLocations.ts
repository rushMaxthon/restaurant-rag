import type {SelectedLocation} from '@/types/app';

export interface LocationSearchResult extends SelectedLocation {
  id: string;
  title: string;
  subtitle: string;
}

export const mockLocations: LocationSearchResult[] = [
  {
    id: 'andheri-west',
    title: 'Andheri West',
    subtitle: 'Mumbai, Maharashtra',
    address: 'Andheri West, Mumbai, Maharashtra',
    city: 'Mumbai',
    latitude: 19.1364,
    longitude: 72.8271,
  },
  {
    id: 'bandra-west',
    title: 'Bandra West',
    subtitle: 'Mumbai, Maharashtra',
    address: 'Bandra West, Mumbai, Maharashtra',
    city: 'Mumbai',
    latitude: 19.0596,
    longitude: 72.8295,
  },
  {
    id: 'koramangala',
    title: 'Koramangala 5th Block',
    subtitle: 'Bengaluru, Karnataka',
    address: 'Koramangala 5th Block, Bengaluru, Karnataka',
    city: 'Bengaluru',
    latitude: 12.9352,
    longitude: 77.6245,
  },
  {
    id: 'hsr-layout',
    title: 'HSR Layout Sector 2',
    subtitle: 'Bengaluru, Karnataka',
    address: 'HSR Layout Sector 2, Bengaluru, Karnataka',
    city: 'Bengaluru',
    latitude: 12.9116,
    longitude: 77.6474,
  },
  {
    id: 'banjara-hills',
    title: 'Banjara Hills Road No. 12',
    subtitle: 'Hyderabad, Telangana',
    address: 'Banjara Hills Road No. 12, Hyderabad, Telangana',
    city: 'Hyderabad',
    latitude: 17.4192,
    longitude: 78.4381,
  },
  {
    id: 'jubilee-hills',
    title: 'Jubilee Hills Check Post',
    subtitle: 'Hyderabad, Telangana',
    address: 'Jubilee Hills Check Post, Hyderabad, Telangana',
    city: 'Hyderabad',
    latitude: 17.432,
    longitude: 78.4071,
  },
  {
    id: 'connaught-place',
    title: 'Connaught Place',
    subtitle: 'New Delhi, Delhi',
    address: 'Connaught Place, New Delhi, Delhi',
    city: 'New Delhi',
    latitude: 28.6315,
    longitude: 77.2167,
  },
  {
    id: 'cyber-city',
    title: 'DLF Cyber City',
    subtitle: 'Gurugram, Haryana',
    address: 'DLF Cyber City, Gurugram, Haryana',
    city: 'Gurugram',
    latitude: 28.4942,
    longitude: 77.0898,
  },
  {
    id: 'salt-lake',
    title: 'Salt Lake Sector V',
    subtitle: 'Kolkata, West Bengal',
    address: 'Salt Lake Sector V, Kolkata, West Bengal',
    city: 'Kolkata',
    latitude: 22.5697,
    longitude: 88.4337,
  },
  {
    id: 't-nagar',
    title: 'T Nagar',
    subtitle: 'Chennai, Tamil Nadu',
    address: 'T Nagar, Chennai, Tamil Nadu',
    city: 'Chennai',
    latitude: 13.0418,
    longitude: 80.2337,
  },
];
