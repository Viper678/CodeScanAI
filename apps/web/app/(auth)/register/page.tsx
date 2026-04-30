import { AuthFormCard } from '@/components/auth/auth-form-card';

export default function RegisterPage() {
  return (
    <AuthFormCard
      title="Create your account"
      description="This placeholder validates locally only. The real registration flow is wired in T1.3."
      submitLabel="Create account"
      alternateHref="/login"
      alternateLabel="Sign in"
    />
  );
}
