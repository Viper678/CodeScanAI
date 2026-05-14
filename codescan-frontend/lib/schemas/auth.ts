import { z } from 'zod';

/**
 * Minimum password length, mirrored from apps/api/app/schemas/auth.py and
 * docs/SECURITY.md §2. Keep this constant in sync if the server ever changes.
 */
export const PASSWORD_MIN_LENGTH = 12;

export const loginSchema = z.object({
  email: z.string().trim().email('Enter a valid email address.'),
  password: z
    .string()
    .min(
      PASSWORD_MIN_LENGTH,
      `Password must be at least ${PASSWORD_MIN_LENGTH} characters long.`,
    ),
});

export const registerSchema = loginSchema;

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
