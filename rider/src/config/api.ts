/**
 * Where the backend is.
 *
 * Debug builds talk to `localhost:8000` and rely on `adb reverse tcp:8000
 * tcp:8000`, which works for the emulator AND a phone on USB - no LAN IP to
 * go stale with the Wi-Fi lease. Release builds take the deployed API.
 */
export const API_BASE_URL = __DEV__ ? 'http://localhost:8000/api' : 'https://api.foodie.example/api';

/** Long enough for a slow 3G cell; short enough that a dead one says so. */
export const REQUEST_TIMEOUT_MS = 15_000;

export const SUPPORT_PHONE = '+919999999999';

/** The rider app's name, as riders see it on the phone and in the app. */
export const APP_NAME = 'PreeRider';
export const APP_VERSION = '1.0.0';
