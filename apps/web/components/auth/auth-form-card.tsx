'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';

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

const authFormSchema = z.object({
  email: z.string().trim().email('Enter a valid email address.'),
  password: z.string().min(12, 'Password must be at least 12 characters long.'),
});

type AuthFormValues = z.infer<typeof authFormSchema>;

type AuthFormCardProps = {
  alternateHref: '/login' | '/register';
  alternateLabel: string;
  description: string;
  submitLabel: string;
  title: string;
};

function notImplementedSubmit() {
  throw new Error('not implemented');
}

export function AuthFormCard({
  alternateHref,
  alternateLabel,
  description,
  submitLabel,
  title,
}: Readonly<AuthFormCardProps>) {
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    formState: { errors, isSubmitting },
    handleSubmit,
    register,
  } = useForm<AuthFormValues>({
    defaultValues: {
      email: '',
      password: '',
    },
    resolver: zodResolver(authFormSchema),
  });

  const onSubmit = handleSubmit(async () => {
    setSubmitError(null);

    try {
      notImplementedSubmit();
    } catch (error) {
      setSubmitError(
        error instanceof Error ? error.message : 'Unable to submit the form.',
      );
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
        <form className="space-y-5" onSubmit={onSubmit}>
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
                alternateHref === '/register'
                  ? 'new-password'
                  : 'current-password'
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
            {submitLabel}
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
