import { AuthGate } from "@/components/AuthGate";
import { ReportsView } from "@/components/ReportsView";

export default function ReportsPage() {
  return (
    <AuthGate>
      <ReportsView />
    </AuthGate>
  );
}
