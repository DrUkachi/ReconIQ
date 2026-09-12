import { redirect } from "next/navigation";

import { AuthCard } from "../components/auth/auth-card";
import { getSession } from "../lib/server-api";
import { auth0 } from "@/lib/auth0";

type AuthSearchParams = {
  screen_hint?: string;
  mode?: string;
};

export default async function AuthPage({
  searchParams,
}: {
  searchParams?: Promise<AuthSearchParams>;
}) {
  if (await getSession()) {
    redirect("/reconciliations");
  }
  if ((await auth0.getSession())?.user?.email) {
    redirect("/auth/complete");
  }

  const params: AuthSearchParams = (await searchParams) ?? {};
  const initialMode =
    params.screen_hint === "signup" || params.mode === "signup" ? "signup" : "login";

  return (
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_#ecfeff_0%,_#f8fafc_35%,_#e2e8f0_100%)] px-4 py-10">
      <AuthCard mode={initialMode} />
    </main>
  );
}
