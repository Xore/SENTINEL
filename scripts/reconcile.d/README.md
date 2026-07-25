# Reconciler appliers (`scripts/reconcile.d/`)

Each **executable** file in this directory is an *applier* for one privileged
resource, driven by the generic reconciler daemon (`scripts/reconciler.py`). The
unprivileged dashboard writes a desired-state file; the root daemon runs the
matching applier to enact it, and rolls it back if the apply fails or a
`confirm`-flagged change is not confirmed before its deadline.

## Naming

The file's basename **is** the resource name and must match
`^[a-z0-9][a-z0-9_-]{0,63}$` (no extension, no path separators — this blocks
traversal). The dashboard writes `<name>.desired.json`; the daemon writes
`<name>.state.json`.

## Contract

The daemon invokes the applier with one of three subcommands. It must be
executable (`chmod +x`) and self-contained.

| Invocation | Job | Exit code |
|---|---|---|
| `<applier> apply <desired.json> <snapshot_dir>` | Snapshot the current live state into `<snapshot_dir>`, then enact `payload` from `<desired.json>`. **Validate your own change** before exiting. | `0` on success; **non-zero** on any failure — the daemon then calls `rollback`. |
| `<applier> rollback <snapshot_dir>` | Restore the state captured during `apply` from `<snapshot_dir>`. | `0` when the system is back to the snapshot. |
| `<applier> report` | Print the current *actual* state as a single JSON object on stdout. | `0`; anything else is treated as "no report". |

Rules:

- **Snapshot first, enact second.** `apply` receives an empty, daemon-created
  `<snapshot_dir>`; write whatever `rollback` will need into it before touching
  the live system.
- **Fail loud.** If the change can't be verified good, exit non-zero so the
  daemon rolls back. This is the whole safety mechanism.
- **Be idempotent.** `apply` may run again for a higher revision; re-applying the
  same payload must be a no-op-equivalent.
- **No secrets on disk.** Desired/state files are world-readable (`0644`).

## The `confirm` / auto-rollback timer

If the desired file has `"confirm": true`, the daemon applies the change but
marks it `pending_confirm` with a deadline (`now + grace_seconds`). The operator
must set `confirmed_revision == revision` (the dashboard's *Keep this change*
button) before the deadline, or the daemon auto-runs `rollback`. Use this for any
change that can lock you out of the box you're reaching it over — e.g. the
network applier (task #29). If you can't click "keep", your connection is gone,
so it reverts and comes back on its own.

## Example desired file

```json
{
  "revision": 3,
  "payload": { "method": "dhcp", "interface": "wlp2s0" },
  "confirm": true,
  "grace_seconds": 120,
  "confirmed_revision": 2
}
```
