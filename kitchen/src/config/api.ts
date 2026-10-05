import { Platform } from 'react-native';

// The Android emulator reaches the host machine through 10.0.2.2; the iOS
// simulator shares the host's loopback. A physical device needs the LAN
// address instead, which the backend's CORS regex already allows.
const DEV_HOST = Platform.OS === 'android' ? '10.0.2.2' : 'localhost';

export const API_BASE_URL = `http://${DEV_HOST}:8000/api`;
