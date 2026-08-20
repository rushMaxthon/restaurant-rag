import { getApp, getApps } from '@react-native-firebase/app';
import {
  getAuth,
  signInWithPhoneNumber,
  type FirebaseAuthTypes,
} from '@react-native-firebase/auth';

let pendingConfirmation: FirebaseAuthTypes.ConfirmationResult | null = null;
let pendingPhoneNumber: string | null = null;
const OTP_REQUEST_TIMEOUT_MS = 45000;

function extractFirebaseErrorDetails(error: unknown) {
  const code =
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    typeof (error as { code?: unknown }).code === 'string'
      ? (error as { code: string }).code
      : null;

  const message =
    error instanceof Error
      ? error.message
      : typeof error === 'object' &&
          error !== null &&
          'message' in error &&
          typeof (error as { message?: unknown }).message === 'string'
        ? (error as { message: string }).message
        : null;

  return { code, message };
}

function logFirebaseAuthEvent(
  label: string,
  extra: Record<string, unknown> = {},
) {
  console.info('[FirebasePhoneAuth]', label, extra);
}

function logFirebaseAuthError(label: string, error: unknown) {
  const { code, message } = extractFirebaseErrorDetails(error);
  console.error('[FirebasePhoneAuth]', label, {
    code,
    message,
    error,
  });
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number) {
  return Promise.race<T>([
    promise,
    new Promise<T>((_, reject) => {
      setTimeout(() => {
        reject(
          new Error(
            'OTP request timed out. Please check Play Services and try again.',
          ),
        );
      }, timeoutMs);
    }),
  ]);
}

function getFirebaseAuthInstance() {
  const apps = getApps();
  if (apps.length === 0) {
    throw new Error(
      'Firebase is not configured on this device. Rebuild the app and try again.',
    );
  }

  const firebaseApp = getApp();
  const authInstance = getAuth(firebaseApp);
  if (
    !authInstance ||
    typeof authInstance.signInWithPhoneNumber !== 'function'
  ) {
    throw new Error(
      'Firebase phone authentication is unavailable right now.',
    );
  }

  logFirebaseAuthEvent('Auth instance ready', {
    appName: firebaseApp.name,
    appId: firebaseApp.options.appId,
    projectId: firebaseApp.options.projectId,
  });

  return authInstance;
}

function mapPhoneAuthError(error: unknown): string {
  const code =
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    typeof (error as { code?: unknown }).code === 'string'
      ? (error as { code: string }).code
      : null;

  switch (code) {
    case 'auth/invalid-phone-number':
      return 'Enter a valid mobile number with the selected country code.';
    case 'auth/missing-phone-number':
      return 'Enter your mobile number before requesting OTP.';
    case 'auth/too-many-requests':
      return 'Too many OTP requests. Please wait a bit and try again.';
    case 'auth/quota-exceeded':
      return 'Firebase OTP quota is exhausted right now. Please try again later.';
    case 'auth/network-request-failed':
      return 'Network error while contacting Firebase. Check your internet connection.';
    case 'auth/code-expired':
      return 'Your OTP expired. Please request a new code.';
    case 'auth/invalid-verification-code':
      return 'The OTP you entered is incorrect.';
    case 'auth/session-expired':
      return 'This verification session expired. Please request a new OTP.';
    case 'auth/missing-verification-code':
      return 'Enter the OTP you received on your phone.';
    case 'auth/app-not-authorized':
      return 'This Firebase app is not authorized for phone authentication.';
    case 'auth/operation-not-allowed':
      return 'Phone authentication is not enabled for this Firebase project.';
    default:
      if (error instanceof Error && error.message) {
        return error.message;
      }
      return 'Unable to verify your mobile number right now.';
  }
}

async function startPhoneNumberSignIn(phoneNumber: string) {
  pendingConfirmation = null;
  pendingPhoneNumber = null;

  try {
    const authInstance = getFirebaseAuthInstance();
    logFirebaseAuthEvent('Sending OTP', { phoneNumber });
    const confirmation = await withTimeout(
      signInWithPhoneNumber(authInstance, phoneNumber),
      OTP_REQUEST_TIMEOUT_MS,
    );
    pendingConfirmation = confirmation;
    pendingPhoneNumber = phoneNumber;
    logFirebaseAuthEvent('OTP send succeeded', {
      phoneNumber,
      verificationId: confirmation.verificationId,
    });
    return {
      verificationId: confirmation.verificationId,
      phoneNumber,
    };
  } catch (error) {
    logFirebaseAuthError('OTP send failed', error);
    clearPendingPhoneVerification();
    throw new Error(mapPhoneAuthError(error));
  }
}

async function confirmPhoneCode(code: string) {
  if (!pendingConfirmation) {
    throw new Error('Start the OTP flow again to continue.');
  }

  try {
    logFirebaseAuthEvent('Verifying OTP', {
      phoneNumber: pendingPhoneNumber,
    });
    const credential = await pendingConfirmation.confirm(code);
    if (!credential) {
      throw new Error('OTP verification did not return a Firebase user.');
    }
    const idToken = await credential.user.getIdToken();
    return {
      uid: credential.user.uid,
      idToken,
      phoneNumber: credential.user.phoneNumber ?? pendingPhoneNumber,
    };
  } catch (error) {
    logFirebaseAuthError('OTP verify failed', error);
    throw new Error(mapPhoneAuthError(error));
  }
}

function clearPendingPhoneVerification() {
  pendingConfirmation = null;
  pendingPhoneNumber = null;
}

async function signOutFirebasePhoneAuth() {
  try {
    if (getApps().length > 0) {
      const authInstance = getFirebaseAuthInstance();
      await authInstance.signOut();
    }
  } catch {
    // Firebase Auth is only used for OTP verification in registration.
  } finally {
    clearPendingPhoneVerification();
  }
}

function getPendingPhoneNumber() {
  return pendingPhoneNumber;
}

export const firebaseAuthService = {
  startPhoneNumberSignIn,
  confirmPhoneCode,
  clearPendingPhoneVerification,
  getPendingPhoneNumber,
  signOutFirebasePhoneAuth,
};
