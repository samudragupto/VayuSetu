import { AuthGate } from "@/components/AuthGate";
import { AlertsView } from "@/components/AlertsView";

export default function AlertsPage() {
  return (
    <AuthGate>
      <AlertsView />
    </AuthGate>
  );
}
