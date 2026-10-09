# Railway project configuration

`railway.ts` is the current project-wide IaC file. The API, web and worker use the repository root, existing Dockerfiles and one Amsterdam replica each. It contains only non-secret defaults and references to existing Railway shared variables. It does not read local environment files, bind a repository, create domains or migrate Supabase.

Local validation (Node 22+):

```sh
npm ci --prefix .railway --ignore-scripts
npm run check --prefix .railway
```

This checks SDK types, graph validity and the intended service boundaries without signing in. It is not a Railway environment plan or a deployment. The official `railway` SDK is pinned in this directory; the Railway CLI is separate and must be version 5.42.1 or newer for this SDK.

Before any separately authorised cloud plan, configure the shared variables referenced by the file in the target Railway environment. Keep keys there, never in this repository or plan output. Choose the reviewed repository/release with root `/`, establish API/web HTTPS origins, and configure CORS, proxy trust and Auth redirects. API/worker use server secrets; the web service references only public build variables. Paid execution, factual rollout and Arize export remain explicitly disabled until their release checks pass. Shared variables are referenced, not created or changed by this file.

The file describes the whole intended environment. Railway treats omitted managed resources as deletions: inspect an existing environment and migrate legacy configuration before using it there. Do not apply a plan that removes unrelated resources, secrets or tracing. Keep the old `deploy/railway-*.json` files only as historical recipes; they are not supported for new services.

See the [product scope](../README.md#pilot-scope), [archived deployment instructions](../archive/docs/deployment.md) and the [official IaC guide](https://docs.railway.com/infrastructure-as-code), checked 2 October 2026. No cloud plan or deployment was run when preparing this configuration.
