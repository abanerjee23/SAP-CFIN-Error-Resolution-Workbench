import type { NextConfig } from "next";

const browserKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "";
let keyRole = "";
try {
  const payload = browserKey.split(".")[1];
  if (payload) keyRole = JSON.parse(Buffer.from(payload, "base64url").toString()).role || "";
} catch {
  // Modern publishable keys are not JWTs.
}
if (browserKey.startsWith("sb_secret_") || keyRole === "service_role") {
  throw new Error("A Supabase secret/service-role key cannot be used in NEXT_PUBLIC variables.");
}

const config: NextConfig = {
  // The local Apple Silicon launcher links dependencies from OS temporary storage
  // to prevent iCloud from offloading them. Standalone tracing follows that link
  // outside the project and cannot package it; production builds keep standalone.
  output: process.env.CFIN_LOCAL_BUILD === "1" ? undefined : "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false,
  allowedDevOrigins: ["127.0.0.1"],
};

export default config;
