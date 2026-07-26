# Collector Enrollment Contract

## Transport and authentication

- Endpoint: `POST /api/pki/enroll` over TLS 1.3 or newer.
- Authentication: `Authorization: Bearer <one-time-token>`.
- Tokens are random secrets stored server-side only as SHA-256 digests and are
  bound to one `(site_id, collector_id)`.
- A token is consumed in the same database transaction that registers the
  issued certificate. Unknown, expired, reused, identity-mismatched, and
  disabled-collector tokens all return the same rejection response.
- Responses use `Cache-Control: no-store`. Tokens and CSR bodies must not be
  logged.

## Request

The JSON body is strict; unknown fields are rejected.

```json
{
  "site_id": "site-a",
  "collector_id": "probe-01",
  "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----\n...\n"
}
```

`site_id` and `collector_id` follow ADR 0009. The CSR signature must be valid,
its common name must equal `collector_id`, and its single organizational unit
must equal `site_id`.

## Success

Status `200`:

```json
{
  "certificate_pem": "-----BEGIN CERTIFICATE-----\n...\n",
  "ca_certificate_pem": "-----BEGIN CERTIFICATE-----\n...\n"
}
```

The response deliberately does not echo identity fields. Before persisting
files, the collector verifies that:

1. the leaf public key matches the private key used for the CSR;
2. the leaf chains to the returned, locally trusted enrollment CA;
3. the leaf has exactly one collector URI SAN, equal to
   `spiffe://sentinel.local/sites/{site_id}/collectors/{collector_id}`;
4. the leaf is currently valid and permits TLS client authentication.

## Errors and retry behavior

Error bodies are non-sensitive and do not distinguish token rejection causes.

| Status | Meaning | Collector behavior |
|---:|---|---|
| `400` | malformed JSON or unsupported request shape | fail immediately |
| `401` | missing or rejected enrollment credential | fail immediately |
| `403`, `404`, `409`, `422` | terminal request/identity rejection | fail immediately |
| `405` | wrong HTTP method | fail immediately |
| `408`, `425`, `429` | temporary client-facing condition | retry; honor `Retry-After` |
| `5xx` | temporary server failure | retry with bounded exponential backoff |

Network failures and timeouts are retryable. A successful response that fails
certificate validation is terminal and no key, leaf, or CA file is persisted.

## Compatibility

This is contract version 1. Additive response fields may be ignored. Removing
or renaming fields, changing the SPIFFE URI, or changing status retry classes
requires a coordinated producer/consumer rollout. Rollback retains the same
database schema and wire format; unused one-time tokens remain valid until
their original expiry.
