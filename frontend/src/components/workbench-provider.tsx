"use client";

import { MantineProvider, createTheme } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import type { ReactNode } from "react";

const theme = createTheme({
  primaryColor: "teal",
  fontFamily: "Inter Variable, Inter, ui-sans-serif, system-ui, sans-serif",
  headings: { fontFamily: "Inter Variable, Inter, ui-sans-serif, system-ui, sans-serif", fontWeight: "700" },
  fontSizes: { xs: "13px", sm: "14px", md: "15px", lg: "17px", xl: "20px" },
  colors: { teal: ["#edf9f7", "#d7f1ed", "#b5e3db", "#80cdc2", "#51b6ab", "#289d92", "#167f78", "#0e6371", "#0a505b", "#063f48"] },
});

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  return <MantineProvider theme={theme}><Notifications position="bottom-right" />{children}</MantineProvider>;
}
