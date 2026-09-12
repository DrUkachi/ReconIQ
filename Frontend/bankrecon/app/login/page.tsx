import { AuthCard } from "../components/auth/auth-card";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_#f0fdfa_0%,_#f8fafc_35%,_#e2e8f0_100%)] px-4 py-10">
      <AuthCard mode="login" />
    </main>
  );
}
