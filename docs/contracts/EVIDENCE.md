# Evidence Bundle Contract

Status: normative, schema version `1`.

An evidence bundle is a deterministic, bounded, site-scoped artifact for
authorized operational export. The foundation package accepts only explicit
caller-supplied byte entries; it never discovers files, reads secrets, queries
the database, or performs authorization.

## Container

- media type: `application/vnd.sentinel.evidence.v1+tar+gzip`;
- one gzip member containing a POSIX USTAR archive;
- gzip uses best compression, timestamp `1970-01-01T00:00:00Z`, OS `255`, and
  no name, comment, or extra fields;
- every tar entry is a regular file with mode `0600`, UID/GID `0`, timestamp
  `1970-01-01T00:00:00Z`, empty owner/link metadata, and no extended records;
- `manifest.json` is first, followed by declared entries in ascending bytewise
  path order; undeclared, duplicate, reordered, or trailing content is invalid.

The same validated metadata and entry bytes must produce the same compressed
bytes and SHA-256 digest.

## Canonical manifest

`manifest.json` is compact UTF-8 JSON with fields in the following order:

```json
{"schema_version":1,"bundle_id":"123e4567-e89b-12d3-a456-426614174000","tenant_id":"tenant-1","site_id":"site-1","capture_from":"2026-07-28T12:00:00Z","capture_to":"2026-07-28T12:05:00Z","generated_at":"2026-07-28T12:05:01Z","producer":"api/1.0.0","entries":[{"path":"status.txt","media_type":"text/plain","size":3,"sha256":"dc51b8c96c2d745df3bd5590d990230a482fd247123599548e0632fdbf97fc22"}]}
```

Timestamps are canonical UTC RFC 3339 values. `capture_to` is strictly after
`capture_from`, the capture window is at most 24 hours, and `generated_at` is
not earlier than `capture_to`. Bundle IDs are canonical lowercase UUIDs.
Tenant and site IDs are bounded lowercase DNS-label-shaped identifiers.
Producer values are bounded printable version identifiers.

Each entry declares its canonical media type, exact uncompressed byte size, and
lowercase SHA-256 digest. Paths are unique, relative forward-slash paths of at
most 100 bytes. Empty components, `.`, `..`, absolute paths, backslashes, NUL,
and the reserved `manifest.json` path are rejected.

## Bounds and verification

| Limit | Value |
|---|---:|
| Entries | 128 |
| One entry | 4 MiB |
| Total entry content | 32 MiB |
| Compressed bundle | 40 MiB |
| Manifest | 1 MiB |

Verification fails closed on malformed compression or tar data, non-canonical
metadata or JSON, unsupported schema versions, unsafe paths, ordering changes,
missing or extra entries, size mismatches, digest mismatches, and trailing
data. A verified bundle establishes internal integrity only; authorization,
audit logging, retention, encryption, transport policy, and export timeouts
belong to the evidence-export integration layer.

## Compatibility and lifecycle

Schema `1` is immutable. Any incompatible manifest or container change requires
a new schema and media type plus parallel producer/consumer tests. Producers
may roll back by returning to schema `1`; consumers reject unknown versions
rather than guessing. Evidence exports are derived artifacts, so rollback does
not require database migration.
