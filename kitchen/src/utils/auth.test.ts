import { ApiError, NETWORK_ERROR_STATUS } from '@services/api';
import type { AuthResponse } from '@/types/app';
import {
  NotBoardAccountError,
  hasErrors,
  loginErrorMessage,
  toKitchenSession,
  validateLoginForm,
} from './auth';

const response = (overrides: Partial<AuthResponse> = {}): AuthResponse => ({
  access_token: 'token',
  token_type: 'bearer',
  role: 'KITCHEN',
  restaurant_id: 'r-1',
  restaurant_location_id: 'l-1',
  user: {
    id: 'u-1',
    full_name: 'Line Cook',
    email: 'cook@example.com',
    role: 'KITCHEN',
  },
  ...overrides,
});

describe('validateLoginForm', () => {
  it('accepts a well-formed email and an 8-character password', () => {
    expect(hasErrors(validateLoginForm(' cook@example.com ', 'password'))).toBe(false);
  });

  it('asks for both fields when both are empty', () => {
    const errors = validateLoginForm('', '');
    expect(errors.email).toBeDefined();
    expect(errors.password).toBeDefined();
  });

  it('refuses a malformed email', () => {
    expect(validateLoginForm('cook@', 'password').email).toMatch(/email/);
  });

  it('refuses a password the API would 422', () => {
    expect(validateLoginForm('cook@example.com', 'short').password).toMatch(/8/);
  });
});

describe('toKitchenSession', () => {
  it('keeps the branch pin a kitchen account carries', () => {
    expect(toKitchenSession(response())).toEqual({
      token: 'token',
      user: { id: 'u-1', fullName: 'Line Cook', email: 'cook@example.com', role: 'KITCHEN' },
      restaurantId: 'r-1',
      restaurantLocationId: 'l-1',
    });
  });

  it.each(['ADMIN', 'OWNER', 'KITCHEN'] as const)('lets %s run a board', role => {
    expect(toKitchenSession(response({ role })).user.role).toBe(role);
  });

  it('refuses a customer whose password was correct', () => {
    expect(() => toKitchenSession(response({ role: 'CUSTOMER' }))).toThrow(
      NotBoardAccountError,
    );
  });
});

describe('loginErrorMessage', () => {
  it('tells a wrong password apart from an unreachable server', () => {
    const wrong = loginErrorMessage(new ApiError('Invalid', 401));
    const offline = loginErrorMessage(new ApiError('x', NETWORK_ERROR_STATUS));
    expect(wrong).toMatch(/incorrect/);
    expect(offline).toMatch(/reach the server/);
    expect(wrong).not.toBe(offline);
  });

  it('explains a customer account rather than calling it a wrong password', () => {
    expect(loginErrorMessage(new NotBoardAccountError())).toMatch(/kitchen board/);
  });

  it('falls back to a generic sentence for anything else', () => {
    expect(loginErrorMessage(new Error('boom'))).toMatch(/Try again/);
  });
});
