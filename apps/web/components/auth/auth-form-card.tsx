'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';
import { useForm, type Path } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { ApiError } from '@/lib/api/client';
import { useLogin, useRegister } from '@/lib/api/auth/use-session';
import {
  loginSchema,
  registerSchema,
  type LoginValues,
  type RegisterValues,
} from '@/lib/schemas/auth';
import { resolvePostLoginDestination } from '@/lib/auth/redirect';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type Mode = 'login' | 'register';

type AuthFormCardProps = {
  alternateHref: '/login' | '/register';
  alternateLabel: string;
  description: string;
  mode: Mode;
  submitLabel: string;
  title: string;
};

type FormValues = LoginValues | RegisterValues;

const FIELD_NAMES = ['email', 'password'] as const satisfies ReadonlyArray<
  keyof FormValues
>;
type FieldName = (typeof FIELD_NAMES)[number];

function isFieldName(value: unknown): value is FieldName {
  return (
    typeof value === 'string' &&
    (FIELD_NAMES as ReadonlyArray<string>).includes(value)
  );
}

/**
 * Map a thrown ApiError to a top-level form-error string and any field-level
 * errors. The mapping table matches docs/API.md §Auth and the codes documented
 * in §Conventions.
 */
function mapAuthError(
  mode: Mode,
  error: unknown,
): { formMessage: string; fieldErrors: Partial<Record<FieldName, string>> } {
  if (!(error instanceof ApiError)) {
    return {
      fieldErrors: {},
      formMessage: 'Something went wrong. Please try again.',
    };
  }

  if (error.status === 401) {
    return {
      fieldErrors: {},
      formMessage: 'Invalid email or password.',
    };
  }

  if (error.status === 409 && mode === 'register') {
    return {
      fieldErrors: { email: 'Email already in use.' },
      formMessage: 'Email already in use.',
    };
  }

  if (error.status === 422) {
    const fieldErrors: Partial<Record<FieldName, string>> = {};
    for (const detail of error.details) {
      const target = detail.loc?.[detail.loc.length - 1];
      if (isFieldName(target) && detail.msg !== undefined) {
        fieldErrors[target] = detail.msg;
      }
    }
    return {
      fieldErrors,
      formMessage:
        Object.keys(fieldErrors).length > 0
          ? 'Please fix the highlighted fields.'
          : error.message,
    };
  }

  if (error.status === 429) {
    return {
      fieldErrors: {},
      formMessage: 'Too many attempts. Please wait and try again.',
    };
  }

  return { fieldErrors: {}, formMessage: error.message };
}

export function AuthFormCard({
  alternateHref,
  alternateLabel,
  description,
  mode,
  submitLabel,
  title,
}: Readonly<AuthFormCardProps>) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const loginMutation = useLogin();
  const registerMutation = useRegister();

  const {
    formState: { errors, isSubmitting },
    handleSubmit,
    register,
    setError,
  } = useForm<FormValues>({
    defaultValues: {
      email: '',
      password: '',
    },
    resolver: zodResolver(mode === 'login' ? loginSchema : registerSchema),
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      const mutation = mode === 'login' ? loginMutation : registerMutation;
      await mutation.mutateAsync(values);
      const destination = resolvePostLoginDestination(
        searchParams?.get('from') ?? null,
      );
      router.replace(destination);
    } catch (error) {
      const { fieldErrors, formMessage } = mapAuthError(mode, error);
      for (const [field, message] of Object.entries(fieldErrors)) {
        if (message !== undefined) {
          setError(field as Path<FormValues>, { message, type: 'server' });
        }
      }
      setSubmitError(formMessage);
    }
  });

  return (
    <Card className="w-full max-w-md border-border/80 bg-card/95 shadow-xl shadow-black/10">
      <CardHeader className="space-y-2">
        <CardTitle className="text-2xl font-semibold tracking-tight">
          {title}
        </CardTitle>
        <CardDescription className="text-sm leading-6">
          {description}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={onSubmit} noValidate>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="user@example.com"
              aria-invalid={errors.email ? 'true' : 'false'}
              aria-describedby={errors.email ? 'email-error' : undefined}
              {...register('email')}
            />
            {errors.email ? (
              <p id="email-error" className="text-sm text-red-500">
                {errors.email.message}
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete={
                mode === 'register' ? 'new-password' : 'current-password'
              }
              placeholder="At least 12 characters"
              aria-invalid={errors.password ? 'true' : 'false'}
              aria-describedby={errors.password ? 'password-error' : undefined}
              {...register('password')}
            />
            {errors.password ? (
              <p id="password-error" className="text-sm text-red-500">
                {errors.password.message}
              </p>
            ) : null}
          </div>

          {submitError ? (
            <div
              role="alert"
              className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-500"
            >
              {submitError}
            </div>
          ) : null}

          <Button
            type="submit"
            size="lg"
            className="w-full bg-primary text-primary-foreground hover:bg-primary/90"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Please wait…' : submitLabel}
          </Button>
        </form>

        <p className="mt-6 text-sm text-muted-foreground">
          {alternateHref === '/register'
            ? 'Need an account? '
            : 'Already have an account? '}
          <Link
            href={alternateHref}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            {alternateLabel}
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
