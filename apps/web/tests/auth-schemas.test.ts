import { describe, expect, it } from 'vitest';

import {
  PASSWORD_MIN_LENGTH,
  loginSchema,
  registerSchema,
} from '@/lib/schemas/auth';

const VALID_INPUT = {
  email: 'user@example.com',
  password: 'a-strong-password',
};

describe('loginSchema', () => {
  it('accepts a well-formed email and password', () => {
    const result = loginSchema.safeParse(VALID_INPUT);
    expect(result.success).toBe(true);
  });

  it('rejects an invalid email', () => {
    const result = loginSchema.safeParse({
      ...VALID_INPUT,
      email: 'not-an-email',
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.path).toEqual(['email']);
    }
  });

  it(`rejects passwords shorter than ${PASSWORD_MIN_LENGTH} chars`, () => {
    const result = loginSchema.safeParse({
      ...VALID_INPUT,
      password: 'short',
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.path).toEqual(['password']);
    }
  });

  it('trims whitespace from the email', () => {
    const result = loginSchema.safeParse({
      ...VALID_INPUT,
      email: '   user@example.com   ',
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.email).toBe('user@example.com');
    }
  });
});

describe('registerSchema', () => {
  it('accepts the same valid input as login', () => {
    expect(registerSchema.safeParse(VALID_INPUT).success).toBe(true);
  });

  it('rejects an empty payload', () => {
    const result = registerSchema.safeParse({});
    expect(result.success).toBe(false);
  });
});
