import { AuthFormCard } from '@/components/auth/auth-form-card';

export default function LoginPage() {
  return (
    <AuthFormCard
      title="Welcome back"
      description="Sign in to resume scanning repositories, uploads, and settings once auth wiring lands in T1.3."
      submitLabel="Sign in"
      alternateHref="/register"
      alternateLabel="Create one"
    />
  );
}
