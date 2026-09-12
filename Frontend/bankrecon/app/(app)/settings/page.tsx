import { SettingsForm } from "@/app/components/dashboard/settings-form";
import { getSettings, requireSession } from "@/app/lib/server-api";

export default async function SettingsPage() {
  await requireSession();
  const settings = await getSettings();

  return <SettingsForm settings={settings} />;
}
