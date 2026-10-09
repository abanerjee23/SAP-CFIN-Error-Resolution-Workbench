# Repository validation — 9 October 2026

The Desktop project was prepared for its initial push to `abanerjee23/SAP-CFIN-Error-Resolution-Workbench`. Checks used locked dependencies, Python 3.12 and Node 22.23.3 locally. Paid models, workflow cutover and Arize export were disabled; database tests used a disposable local PostgreSQL 17 container with pgvector 0.8.6.

| Check | Result |
| --- | --- |
| Python lint: `uv run ruff check . ../examples` | Passed. |
| Backend suite with `CFIN_POSTGRES_CONTAINER` configured | 786 passed; no skipped database execution probe. |
| Example-client unittest suite | 6 passed. |
| Frontend TypeScript check | Passed. |
| Local optimized Webpack build | Passed; all seven application routes built. |
| Railway SDK types and graph | Passed offline; three services, no cloud calls. |
| Complete `make check` after launcher correction | Passed. |
| Promptfoo Error Analysis policy suite | 5 passed, 0 failures/errors; deterministic, no provider calls. |
| Deployment Dockerfiles | Frontend standalone Turbopack build and backend locked dependency build passed. |
| Container HTTP smoke checks | Standalone frontend served the workbench; backend `/health` returned successfully. |
| Browser smoke check | Dashboard, eight-column Case Board, search filtering, mapping-case summary and Case chat rendered correctly. |
| npm production dependency audit | 0 vulnerabilities. |

The full npm audit reported 7 advisories in development/build dependencies (2 moderate, 5 high), in the Tailwind 3 dependency tree. npm's proposed complete fix requires Tailwind 4, a major migration. The current styling system remains on Tailwind 3; the build-tool advisory remediation needs a separate compatibility review. Passing functional tests does not establish that these development dependencies are free of vulnerabilities.

## Preparation changes

- Moved `FRONTEND_DESIGN.md` and `RE-BUILD.md` into `docs/`; the root contains only `README.md` as Markdown documentation.
- Updated README status, repository structure, setup/check commands and the distinction between the current browser-local demo and backend implementation.
- Repaired documentation links following the move and archive reorganization. Historical evaluation outputs remain local and are described as excluded from Git.
- Corrected Git ignore rules to exclude dependency/build symlinks as well as directories. Local environment files, generated caches and evaluation outputs remain excluded.
- Updated the launcher and Makefile so Railway checks use the same supported Node 22 runtime as the frontend, even when the shell defaults to Node 18.
- Recreated the copied Python environment and moved stale Python caches aside. Rebuilt the initial Git object cache from working files because copied cloud placeholders blocked object reads; the original cache/index were preserved under ignored `.local-runtime/`.

## Scope of the evidence

These checks establish local software behavior, executable database guards and container startup. They do not establish live SAP integration, cloud migration/deployment, production authentication of the current demo, durable demo attachment storage, provider-backed model quality or measured analyst time savings. Those remain the release steps documented in the README.
