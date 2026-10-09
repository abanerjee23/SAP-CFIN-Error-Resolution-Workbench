// Offline SDK validation only. Never instantiate an API client or load .env.
import assert from "node:assert/strict";
import { createRailwayContext, project, validateGraph } from "railway/iac";
import definition from "./railway.ts";

const desired = await definition(createRailwayContext({ environment: "offline-check" }), project);
const graph = { version: 1, project: { name: desired.name }, environments: [], resources: desired.resources, edges: [] };
assert.deepEqual(validateGraph(graph), []);
assert.deepEqual(desired.resources.map(resource => resource.name), ["api", "web", "worker"]);
for (const resource of desired.resources) {
  assert.equal(resource.type, "service");
  assert.equal(resource.source.rootDirectory, "/");
  assert.equal(resource.build.builder, "DOCKERFILE");
  assert.deepEqual(resource.deploy.multiRegionConfig, { "europe-west4-drams3a": { numReplicas: 1 } });
  assert.equal(resource.deploy.restartPolicyType, "ON_FAILURE");
  assert.equal(resource.deploy.restartPolicyMaxRetries, 5);
}
const [api, web, worker] = desired.resources;
assert.equal(api.deploy.healthcheckPath, "/health");
assert.equal(web.deploy.healthcheckPath, "/");
assert.equal(worker.deploy.healthcheckPath, undefined);
assert.equal(worker.deploy.startCommand, "python -m cfin.worker");
assert.deepEqual(Object.keys(web.variables).sort(), ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "NEXT_PUBLIC_SUPABASE_URL"]);
for (const resource of [api, worker]) {
  assert.equal(resource.variables.LOG_ONLY_ENABLED.value, "false");
  assert.equal(resource.variables.PAID_MODELS_ENABLED.value, "false");
  assert.equal(resource.variables.MODEL_RUN_BUDGET_USD.value, "1.00");
  assert.equal(resource.variables.MODEL_MONTHLY_BUDGET_USD.value, "10.00");
  for (const name of ["SUPABASE_SECRET_KEY", "OPENAI_API_KEY", "ARIZE_API_KEY"]) {
    assert.equal(resource.variables[name].type, "sharedReference");
  }
}
console.log("Railway SDK types and graph validated offline: three services; no cloud calls.");
