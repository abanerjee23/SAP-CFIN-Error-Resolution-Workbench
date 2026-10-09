import { defineRailway, project, service } from "railway/iac";
import type { DeployConfig } from "railway/iac";

// Settings only: bind the reviewed repository/release separately. No cloud state
// or local .env values are read while evaluating this file.
export default defineRailway((ctx) => {
  const deployment: DeployConfig = {
    restartPolicyType: "ON_FAILURE",
    restartPolicyMaxRetries: 5,
    multiRegionConfig: { "europe-west4-drams3a": { numReplicas: 1 } },
  };
  const backend = {
    LOG_ONLY_ENABLED: "false",
    PAID_MODELS_ENABLED: "false",
    MODEL_AGENT_1: "gpt-6-luna",
    MODEL_AGENT_2: "gpt-6.1-sol",
    MODEL_AGENT_3: "gpt-6.1-sol",
    MODEL_AGENT_4: "gpt-6.1-sol",
    MODEL_REASONING_EFFORT: "medium",
    MODEL_RUN_BUDGET_USD: "1.00",
    MODEL_MONTHLY_BUDGET_USD: "10.00",
    STAGE_TIMEOUT_SECONDS: "60",
    STAGE_MAX_RETRIES: "1",
    SUPABASE_URL: ctx.shared.SUPABASE_URL,
    SUPABASE_PUBLISHABLE_KEY: ctx.shared.SUPABASE_PUBLISHABLE_KEY,
    SUPABASE_SECRET_KEY: ctx.shared.SUPABASE_SECRET_KEY,
    OPENAI_API_KEY: ctx.shared.OPENAI_API_KEY,
    ARIZE_ENABLED: "false",
    ARIZE_API_KEY: ctx.shared.ARIZE_API_KEY,
    ARIZE_SPACE_ID: ctx.shared.ARIZE_SPACE_ID,
    ARIZE_PROJECT_NAME: "cfin-document-error-analysis",
    ARIZE_API_URL: "https://api.arize.com/v2",
    ARIZE_OTLP_ENDPOINT: "https://otlp.arize.com/v1/traces",
  };
  const api = service("api", {
    root: "/",
    build: { builder: "DOCKERFILE", dockerfilePath: "deploy/Dockerfile.backend" },
    deploy: deployment,
    healthcheck: "/health",
    env: {
      ...backend,
      CORS_ORIGINS: ctx.shared.CORS_ORIGINS,
      FORWARDED_ALLOW_IPS: ctx.shared.FORWARDED_ALLOW_IPS,
    },
  });
  const web = service("web", {
    root: "/",
    build: { builder: "DOCKERFILE", dockerfilePath: "deploy/Dockerfile.frontend" },
    deploy: deployment,
    healthcheck: "/",
    env: {
      NEXT_PUBLIC_SUPABASE_URL: ctx.shared.SUPABASE_URL,
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: ctx.shared.SUPABASE_PUBLISHABLE_KEY,
      NEXT_PUBLIC_API_URL: ctx.shared.NEXT_PUBLIC_API_URL,
    },
  });
  const worker = service("worker", {
    root: "/",
    build: { builder: "DOCKERFILE", dockerfilePath: "deploy/Dockerfile.backend" },
    deploy: deployment,
    start: "python -m cfin.worker",
    env: backend,
  });
  return project(ctx.projectName || "cfin-exception-management", {
    resources: [api, web, worker],
  });
});
