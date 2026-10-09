# Saved case read API v1

This API exposes saved case facts, state, human records and permitted original evidence without browser access. GET requests never call a model, run SAP tools or change case business state. Short-lived listing snapshots and minimal access audit are administrative read records. This is a platform-neutral JSON contract; it does not include a Joule connector, MCP server, external case writes or SAP actions.

FastAPI publishes the concrete response schemas in `/openapi.json` and interactive documentation at `/docs`. Source: [`case_read_api.py`](../../backend/src/cfin/case_read_api.py). The [Python consumer](../../examples/read_case.py) checks pagination, case versions, JSON text and unchanged-byte SHA-256 parity. Its offline tests make no network or model calls.

## Credentials and authority

A signed-in workspace `process_owner` issues and revokes credentials through dedicated management endpoints. These operations use the owner's existing portal bearer token. An issued opaque `cfin_read_…` token is a distinct machine identity; it cannot impersonate that owner and is not a Supabase service credential or JWT. The database stores its SHA-256 digest, explicit workspace/scopes, issuer, expiry and revocation state. The raw token is returned once; store it privately in the consumer's secret manager.

| Scope | Permitted resources |
| --- | --- |
| `cases:read` | Case listing, saved case projection (including factual extraction), selected evidence, activity and attributed human records. |
| `evidence:read` | Registered original source JSON/text and exact-byte downloads. Both scopes are needed by the complete example consumer. |

`cases:read` includes extracted raw text and exact quotations, which can cover an entire original. It is not a log-content redaction scope. `evidence:read` separately controls retrieval of the independently hash-verified stored originals. Grant either capability only to a consumer authorised for the content it exposes.

Each token covers one explicitly chosen workspace. Expiry is 1–90 days (30 by default); revocation and the issuer's continuing `process_owner` membership are checked on every read. A caller's explicit machine scope is its authority; it does not inherit a SAP/Joule end user's permissions. Historical references receive independent current eligibility/access checks. Withdrawn history may be withheld while the current-log summary remains readable.

Use HTTPS for production. Plain HTTP is accepted only for localhost/loopback development. Tokens belong in the `Authorization: Bearer …` header, never URLs, source files, screenshots or logs. Behind an HTTPS reverse proxy, configure Uvicorn `FORWARDED_ALLOW_IPS` with only the trusted ingress IPs/networks so it can correctly recognise the external scheme. The default trusts loopback only; an unconfigured production edge can make valid external HTTPS requests appear HTTP and be rejected. Do not parse/trust arbitrary forwarded headers inside the application. GET responses are `Cache-Control: no-store`. Avoid following redirects with credentials; the example refuses them. API/worker server secrets never belong in an external consumer.

### Issue a credential

```http
POST /api/workspaces/{workspace_id}/read-credentials
Authorization: Bearer <signed-in-process-owner-token>
Content-Type: application/json

{
  "label": "Saved-case test consumer",
  "scopes": ["cases:read", "evidence:read"],
  "expires_in_days": 30
}
```

The typed response supplies `credential_id`, `workspace_id`, `label`, `scopes`, `expires_at` and a one-time `read_token`. Save only the nonsecret credential ID in operational notes; transfer the token directly to private secret storage. Issuance creates a security-sensitive access grant and must be an explicit administrator action, not an automatic side effect of opening a case.

Revoke using the same signed-in owner authority:

```http
POST /api/workspaces/{workspace_id}/read-credentials/{credential_id}/revoke
Authorization: Bearer <signed-in-process-owner-token>
```

The response is `{"revoked": true, "credential_id": "…"}`. The machine token cannot call these management endpoints.

## Resources

Every machine GET requires `workspace_id` plus its machine bearer token.

| GET path | Additional parameters | Response |
| --- | --- | --- |
| `/api/v1/cases` | Optional `status`, `workflow_version` (`legacy-v1` or `log-only-v1`), `limit`, `cursor` | Stable listing snapshot, expiry, total, summary items and `next_cursor`. |
| `/api/v1/cases/{case_id}` | Optional `case_version` | Case/workspace/version, factual or legacy result, ownership/review/work state, analysis state and original source metadata. |
| `/api/v1/cases/{case_id}/extraction` | Required `case_version`; optional `limit`, `cursor` | All saved factual entries, bound to the analysis run and case version. |
| `/api/v1/cases/{case_id}/selected-evidence` | Required `case_version`; optional `limit`, `cursor` | The selected entries with their actual saved content and source locators. |
| `/api/v1/cases/{case_id}/activity` | Required `case_version`; optional `limit`, `cursor` | Allowlisted attributed activity, excluding internal worker payloads. |
| `/api/v1/cases/{case_id}/records` | Required `case_version`; optional `limit`, `cursor` | Reviews, investigation milestones, validation comparisons and resolution records, separately attributed as recorded human history. |
| `/api/v1/cases/{case_id}/sources/{source_id}` | Required `case_version`, `source_version` | Complete UTF-8 original text, exact source binding, filename, byte size and SHA-256. |
| `/api/v1/cases/{case_id}/sources/{source_id}/download` | Required `case_version`, `source_version` | Unchanged source bytes. |

Pagination defaults to 25 items, allows 1–100 per page and returns opaque `next_cursor` values. Case lists are limited to 1,000 matching records per snapshot; narrow supported filters for larger workspaces. Listing snapshots expire after 10 minutes. Keep workspace, filters and page size constant across pages; do not edit cursors or treat them as permission tokens.

Read the case once to obtain `case_version`, then pin every extraction/record/source read to that version. Any case change returns 409 instead of combining new state with old pages. On 409, discard the partial result, reread the case and restart with its new version; bound retries. An expired list likewise requires restarting the whole listing. A cited historical case is a separate authorised read with its own version, not an implicit extension of current-case permissions.

The `analysis` object distinguishes saved publication from the latest request. `stale=true`, `latest_run_state` and `latest_failure` explain why an earlier saved brief may remain visible after a replacement fails. A result of `null` means no saved output is available. `result_kind='legacy'` preserves a legacy diagnosis's meaning; `/extraction` returns 409 for legacy cases instead of fabricating a factual extraction. Legacy originals can have `readable=null` when line metadata was never recorded.

### Minimal read and source response

```http
GET /api/v1/cases/{case_id}?workspace_id={workspace_id}
Authorization: Bearer <scoped-read-token>
Accept: application/json
```

Use the returned source's `source_id`, `source_version` and `content_sha256`, together with the case's `case_version`, for its original read. The source response is typed as:

```json
{
  "api_version": "v1",
  "case_id": "33333333-3333-4333-8333-333333333333",
  "case_version": 3,
  "source_id": "original-source-id",
  "source_version": "1",
  "filename": "original-log.txt",
  "content_type": "text/plain",
  "encoding": "utf-8",
  "sha256": "<64-character SHA-256 digest>",
  "byte_size": 13,
  "text": "E item=0001\r\n"
}
```

This shape is illustrative, not a real model result. UTF-8 encoding of `text` must exactly reproduce the original byte size and SHA-256, including any BOM and line terminators. Compare those values against source metadata from the same case snapshot and against `/download`. Reject mismatches. Do not normalize newlines, strip a BOM or export an excerpt as a complete original.

## Run the safe consumer

Supply the following through your shell/secret manager without placing real tokens in command history:

- `CFIN_API_URL`: HTTPS API origin (loopback HTTP is allowed for local tests).
- `CFIN_WORKSPACE_ID`: the credential's workspace UUID.
- `CFIN_READ_TOKEN`: the privately stored opaque read token.

```sh
# Lists every page and prints only the number of accessible cases.
python3 examples/read_case.py

# Retrieves one consistent case, human records and all permitted originals.
python3 examples/read_case.py --case-id 33333333-3333-4333-8333-333333333333

# Optional explicit private local export after every check passes.
python3 examples/read_case.py --case-id 33333333-3333-4333-8333-333333333333 --output-dir ./private-case

# Offline consumer tests: no credentials, model calls or network access.
python3 -m unittest discover -s examples -p 'test_*.py'
```

The client allows one full restart after a version/snapshot conflict, rejects cross-version pages, refuses redirects, bounds response sizes/page counts and verifies JSON/raw original parity. It prints no token, source content or private response body. Optional export creates a new directory with mode 0700 and files with mode 0600; remote filenames never become local paths. Client checks complement server authorization; they do not prove the semantic accuracy of the factual brief.

## Errors and release scope

| Status | Meaning and consumer handling |
| --- | --- |
| 400 | HTTPS is required for this destination. Correct the origin; do not bypass TLS. |
| 401 | Missing/malformed machine token, or missing owner authentication for management. |
| 403 | Workspace/scope/expiry/revocation/issuer eligibility denies access. Stop and obtain appropriate administrator access. |
| 404 | The permitted case or original source is unavailable. Do not guess alternate private identifiers. |
| 409 | Snapshot expired/changed, or factual extraction is unavailable for this result. Restart a changed snapshot once; respect explicit legacy/unavailable state. |
| 422 | Invalid request/cursor, unsupported source representation, or a listing exceeds its bound. Correct the request or narrow filters. |
| 503 | Saved-case read service unavailable. Retry according to a bounded operational policy. |

The additive log-only migration defines credential, snapshot and audit boundaries. `LOG_ONLY_ENABLED` controls new factual intake/dispatch; it is independent of paid execution and does not make pre-existing saved reads perform model work. Local PostgreSQL/software verification is recorded in [BUILD](../BUILD.md). Provisioning credentials, applying a cloud migration, validating hosted HTTPS, human semantic review and customer-specific Joule configuration remain explicit operational actions; documentation/examples do not perform them.
