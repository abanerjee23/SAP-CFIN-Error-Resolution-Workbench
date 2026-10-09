import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/inter";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./globals.css";
import { WorkbenchProvider } from "@/components/workbench-provider";

export const metadata: Metadata = {
  title: "AIF Resolution Workbench",
  description: "A pilot workspace for resolving Central Finance document exceptions.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body><WorkbenchProvider>{children}</WorkbenchProvider></body>
    </html>
  );
}
