import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/hooks/useAuth";

import "./globals.css";

export const metadata: Metadata = {
  title: "VayuSetu · Authority control room",
  description: "A clear operational view of citizen air-quality signals, satellite context and 12-hour forecasts.",
  applicationName: "VayuSetu",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#123b8d",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
