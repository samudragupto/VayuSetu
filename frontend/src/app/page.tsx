import { AuthGate } from "@/components/AuthGate";
import { OverviewDashboard } from "@/components/OverviewDashboard";

export default function OverviewPage() {
  return (
    <AuthGate>
      <OverviewDashboard />
    </AuthGate>
  );
}
