import { AuthFormCard } from '@/components/auth/auth-form-card';

// Auth pages depend on the request (cookies, ?from query) so opt out of
// static rendering. Otherwise Next 14 errors on useSearchParams without a
// Suspense boundary at build time.
export const dynamic = 'force-dynamic';

export default function RegisterPage() {
  return (
    <AuthFormCard
      mode="register"
      title="Create your account"
      description="Use a 12+ character password. You can change your email later from settings."
      submitLabel="Create account"
      alternateHref="/login"
      alternateLabel="Sign in"
    />
  );
}
