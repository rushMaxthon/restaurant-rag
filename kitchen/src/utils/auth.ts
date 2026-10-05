import { ApiError, NETWORK_ERROR_STATUS } from '@services/api';
import type {
  AuthResponse,
  BoardRole,
  KitchenSession,
  UserRole,
} from '@/types/app';

// Same floor as UserLogin.password on the API. Checking it here saves a round
// trip that could only come back 422.
export const MIN_PASSWORD_LENGTH = 8;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export interface LoginFormErrors {
  email?: string;
  password?: string;
}

export const validateLoginForm = (
  email: string,
  password: string,
): LoginFormErrors => {
  const errors: LoginFormErrors = {};
  const trimmed = email.trim();
  if (!trimmed) {
    errors.email = 'Enter the email for this kitchen account.';
  } else if (!EMAIL_PATTERN.test(trimmed)) {
    errors.email = 'That does not look like an email address.';
  }
  if (!password) {
    errors.password = 'Enter the password.';
  } else if (password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Passwords are at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  return errors;
};

export const hasErrors = (errors: LoginFormErrors): boolean =>
  Boolean(errors.email || errors.password);

const BOARD_ROLES: readonly BoardRole[] = ['ADMIN', 'OWNER', 'KITCHEN'];

export const isBoardRole = (role: UserRole): role is BoardRole =>
  (BOARD_ROLES as readonly UserRole[]).includes(role);

// Thrown when the password was right but the account cannot run a board.
// /auth/login answers a customer like anyone else, so this app is where a
// customer login has to stop — otherwise every board call after it is a 403.
export class NotBoardAccountError extends Error {
  constructor() {
    super('not-board-account');
    this.name = 'NotBoardAccountError';
  }
}

export const toKitchenSession = (response: AuthResponse): KitchenSession => {
  if (!isBoardRole(response.role)) {
    throw new NotBoardAccountError();
  }
  return {
    token: response.access_token,
    user: {
      id: response.user.id,
      fullName: response.user.full_name,
      email: response.user.email,
      role: response.role,
    },
    restaurantId: response.restaurant_id,
    restaurantLocationId: response.restaurant_location_id,
  };
};

// One sentence for the banner under the form. A wrong password and an
// unreachable server need different actions from the person at the tablet,
// so they are never folded into one "something went wrong".
export const loginErrorMessage = (error: unknown): string => {
  if (error instanceof NotBoardAccountError) {
    return 'This account cannot open the kitchen board. Sign in with a kitchen, owner or admin account.';
  }
  if (error instanceof ApiError) {
    if (error.status === NETWORK_ERROR_STATUS) {
      return 'Cannot reach the server. Check the tablet is online and try again.';
    }
    // authenticate_user answers a deactivated account with the same 401 as a
    // wrong password, so this sentence has to cover both.
    if (error.status === 401) {
      return 'Email or password is incorrect, or the account is switched off.';
    }
  }
  return 'Sign-in failed. Try again in a moment.';
};
