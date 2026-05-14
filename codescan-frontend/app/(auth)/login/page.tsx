import { AuthFormCard } from '@/components/auth/auth-form-card';

// Auth pages depend on the request (cookies, ?from query) so opt out of
// static rendering. Otherwise Next 14 errors on useSearchParams without a
// Suspense boundary at build time.
export const dynamic = 'force-dynamic';

export default function LoginPage() {
  return (
    <AuthFormCard
      mode="login"
      title="Welcome back"
      description="Sign in to resume scanning your repositories, uploads, and findings."
      submitLabel="Sign in"
      alternateHref="/register"
      alternateLabel="Create one"
    />
  );
}
