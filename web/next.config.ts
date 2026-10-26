import type { NextConfig } from "next";
import path from "path";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname),
};

export default withSentryConfig(nextConfig, {
  silent: true,
  // Build diagnostics are optional; do not send build metadata to Sentry.
  telemetry: false,
  disableLogger: true,
});
