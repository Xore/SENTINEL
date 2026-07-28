# Collector Update Manifest v1

This contract is the release-side authority for ADR 0006. It fixes the bytes
that an offline release engineer signs and the future node updater verifies.
The machine-readable shape is
[`contracts/collector-update-manifest-v1.schema.json`](../../contracts/collector-update-manifest-v1.schema.json).

## Architecture decisions

- Field collectors use ADR 0006's host-level systemd service and versioned
  symlink. Docker Compose remains the hub/dev deployment mechanism; a
  container must not replace its own image from inside its writable layer.
- A root-owned updater polls a fixed backend endpoint at a bounded interval
  (initially 24 hours). The unprivileged collector never supplies a manifest,
  URL, path, command, or update instruction.
- Release manifests are signed offline. The Ed25519 private key is never stored
  in GitHub Actions, a production backend, a collector image, or the repository.
  CI may build artifacts and emit digests, but an operator signs the final
  manifest outside CI. The provisioned public key is the initial node trust
  root.
- Manifest validity is bounded to at most 31 days. `not_before` is inclusive;
  `expires_at` is exclusive. This limits replay of a valid but withdrawn
  higher-version release.
- v1 production platforms are exactly `linux/amd64` and `linux/arm64`. Windows
  remains a development/test platform. No `linux/arm/v7` artifact is accepted
  until a real 32-bit fleet requirement is recorded.
- The privileged verifier/installer remains a separate entry point under
  `collector/updater/`; sharing a source root does not share runtime privileges.

The future fixed discovery paths are:

```text
GET /api/v1/collector/updates/{platform}/latest
GET /api/v1/collector/updates/{platform}/{collector_version}/artifact
```

`platform` is encoded as one path segment by replacing `/` with `-`
(`linux-amd64` or `linux-arm64`). The updater constructs these paths from
validated local/platform and signed/version values. A manifest never carries a
URL or filesystem path.

## Schema and field rules

| Field | Rule |
|---|---|
| `schema_version` | Integer `1` |
| `collector_version` | Stable SemVer-shaped SENTINEL v2 release, exactly `2.x.y`; no prefix, build metadata, or prerelease |
| `platform` | `linux/amd64` or `linux/arm64` |
| `sha256` | 64 lowercase hexadecimal characters |
| `size_bytes` | 1 through 268,435,456 bytes |
| `not_before` | Exact UTC seconds: `YYYY-MM-DDTHH:MM:SSZ`, inclusive |
| `expires_at` | Same format, after `not_before`, exclusive, at most 31 days later |
| `min_supported_from_version` | Oldest installed `2.x.y` version allowed to apply this release; cannot exceed `collector_version` |
| `rollback` | `false` for normal releases; `true` is explicit signed downgrade authority |
| `signing_key_id` | First eight bytes of SHA-256 over the raw 32-byte Ed25519 public key, encoded as 16 lowercase hex characters |
| `signature` | Standard padded base64 of the 64-byte Ed25519 signature |

Unknown or missing fields are invalid. The node must additionally reject:

- a platform other than its detected platform;
- a normal manifest whose version is not strictly greater than the persisted
  current version;
- a current version lower than `min_supported_from_version`;
- a rollback manifest that is not explicitly authorized by local rollout
  policy, even when its signature is valid;
- a key ID absent from its root-owned trust store;
- an artifact whose exact size or SHA-256 differs from the signed values.

## Canonical bytes

The Ed25519 signature covers compact UTF-8 JSON containing every field except
`signature`, with keys sorted lexicographically and no insignificant
whitespace. All v1 string domains are ASCII. Python implementations must
produce the equivalent of:

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

The complete manifest file uses the same compact sorted-key encoding after
adding `signature`. A verifier may ignore surrounding whitespace (allowing the
release CLI's final newline) but must reject internal whitespace, reordered or
duplicate keys, unknown fields, trailing JSON values, and alternate encodings.

Compatibility fixtures live in
`backend/api/internal/updatemanifest/testdata/`:

- `golden-artifact.bin`;
- `golden-public-key.pem`;
- `golden-payload.json` (the exact signed bytes);
- `golden-manifest.json` (the exact complete manifest).

The fixture key is test-only and is not a release trust root.

## Verification order

The updater performs these checks in order:

1. bound the response size, parse only canonical JSON, reject unknown fields;
2. validate schema, types, platform, version, time, size, digest, and key ID;
3. load the trusted public key matching `signing_key_id`;
4. verify Ed25519 over the canonical payload;
5. enforce `not_before <= now < expires_at`, platform, compatibility, monotonic
   version, and separately authorized rollback policy;
6. download from the fixed derived path into the install filesystem;
7. enforce downloaded byte count while streaming and compare size/SHA-256;
8. only then pass the staged artifact to ADR 0006's atomic installer.

Network TLS is defense in depth. A successful HTTPS or mTLS request never
substitutes for manifest and artifact verification.

## Offline CLI

From `backend/api/`:

```text
go run ./cmd/update-manifest keygen \
  --private-key /offline/release-private.pem \
  --public-key ./release-public.pem

go run ./cmd/update-manifest sign \
  --artifact ./sentinel-collector-linux-amd64 \
  --collector-version 2.3.1 \
  --platform linux/amd64 \
  --not-before 2026-07-28T00:00:00Z \
  --expires-at 2026-08-20T00:00:00Z \
  --min-supported-from-version 2.0.0 \
  --private-key /offline/release-private.pem \
  --output ./collector-update-manifest.json

go run ./cmd/update-manifest verify \
  --manifest ./collector-update-manifest.json \
  --artifact ./sentinel-collector-linux-amd64 \
  --public-key ./release-public.pem
```

Key and manifest outputs are create-only: the CLI refuses to overwrite an
existing file. Private keys are created with mode `0600` and public
keys/manifests with `0644` on POSIX systems. Release procedures must execute
`sign` on an offline machine and publish only the public key, artifact, and
signed manifest.
