import type { CSSProperties } from "react";

type IconName = "cases" | "search" | "chevron" | "close" | "refresh" | "document" | "arrow" | "info" | "check" | "clock" | "preview" | "lock" | "external";
const paths: Record<IconName, string> = {
  cases: "M8 5V3h8v2M4 5h16v15H4zM4 10h16M10 10v3h4v-3",
  search: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM16 16l5 5",
  chevron: "m9 5 7 7-7 7",
  close: "m6 6 12 12M6 18 18 6",
  refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 3M18 18a8 8 0 0 1-13-3",
  document: "M14 3H5v18h14V8l-5-5ZM14 3v5h5M8 12h8M8 16h6",
  arrow: "M4 12h16m-6-6 6 6-6 6",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 11v6M12 7h.01",
  check: "m5 12 4 4L19 6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3 2",
  preview: "M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12ZM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  lock: "M7 10V7a5 5 0 0 1 10 0v3M5 10h14v11H5zM12 14v3",
  external: "M14 3h7v7M21 3 10 14M10 3H3v18h18v-7",
};

export function Icon({ name, size = 18, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}><path d={paths[name]} /></svg>;
}
