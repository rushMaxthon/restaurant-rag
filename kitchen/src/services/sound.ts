import { Vibration } from 'react-native';
import Sound from 'react-native-sound';

// The new-order chime: two rising tones, 0.4s, generated into
// android/app/src/main/res/raw and the iOS bundle as new_order.wav.
//
// Unlike the web board there is no "tap to enable sound" step — a native app
// may play audio without a prior gesture, so a board restored from a saved
// session is never silently muted.
const CHIME_FILE = 'new_order.wav';

// A short double buzz for a phone or tablet with its volume down. The flash
// on the ticket stays the primary signal; sound and vibration are extras.
const VIBRATION_PATTERN = [0, 120, 80, 120];

let chime: Sound | null = null;
let loading = false;

const load = () => {
  if (chime || loading) {
    return;
  }
  loading = true;
  try {
    // Playback plays through the ring/silent switch — a tablet left on silent
    // must still announce an order — and mixes with other audio rather than
    // stopping it.
    Sound.setCategory('Playback', true);
    const sound = new Sound(CHIME_FILE, Sound.MAIN_BUNDLE, error => {
      loading = false;
      chime = error ? null : sound;
    });
  } catch {
    loading = false;
    chime = null;
  }
};

export const prepareChime = (): void => load();

export const playNewOrderAlert = (): void => {
  Vibration.vibrate(VIBRATION_PATTERN);
  if (!chime) {
    load();
    return;
  }
  try {
    chime.stop(() => chime?.play());
  } catch {
    // Audio is a courtesy; the highlighted ticket is the real signal.
  }
};
