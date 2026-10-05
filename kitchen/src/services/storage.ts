import AsyncStorage from '@react-native-async-storage/async-storage';
import type { KitchenSession } from '@/types/app';

const KEYS = {
  session: 'kitchen.session',
  soundOn: 'kitchen.soundOn',
  branchId: 'kitchen.branchId',
} as const;

// Every read degrades to "nothing stored" and every write to "remembered for
// this run only". A board that cannot persist a preference must still run.
const read = async (key: string): Promise<string | null> => {
  try {
    return await AsyncStorage.getItem(key);
  } catch {
    return null;
  }
};

const write = async (key: string, value: string | null): Promise<void> => {
  try {
    if (value === null) {
      await AsyncStorage.removeItem(key);
    } else {
      await AsyncStorage.setItem(key, value);
    }
  } catch {
    // Remembered in memory for as long as the app runs.
  }
};

const isSession = (value: unknown): value is KitchenSession => {
  const candidate = value as Partial<KitchenSession> | null;
  return (
    typeof candidate?.token === 'string' &&
    typeof candidate.user?.id === 'string' &&
    typeof candidate.user.role === 'string'
  );
};

export const storage = {
  async loadSession(): Promise<KitchenSession | null> {
    const raw = await read(KEYS.session);
    if (!raw) {
      return null;
    }
    try {
      const parsed: unknown = JSON.parse(raw);
      // A shape from an older build is dropped rather than half-trusted.
      return isSession(parsed) ? parsed : null;
    } catch {
      return null;
    }
  },
  saveSession: (session: KitchenSession | null) =>
    write(KEYS.session, session ? JSON.stringify(session) : null),

  // Sound defaults ON: a board that is silent until somebody finds a switch
  // is a board that misses its first order.
  async loadSoundOn(): Promise<boolean> {
    return (await read(KEYS.soundOn)) !== 'off';
  },
  saveSoundOn: (on: boolean) => write(KEYS.soundOn, on ? 'on' : 'off'),

  loadBranchId: () => read(KEYS.branchId),
  saveBranchId: (branchId: string | null) => write(KEYS.branchId, branchId),
};
