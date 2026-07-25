"""Validation for dashboard-editable configuration (roadmap P1, task #49).

Pure, dependency-free checks so a bad settings payload is rejected with a clear,
specific message BEFORE it is merged and persisted — rather than silently stored
and breaking a check loop later. `validate_settings()` returns a list of human
error strings (empty means valid); it inspects only the sections actually present
in the partial update, so a UI form that submits one section is judged on that
section alone.

Nothing here talks to a database or the network; app.py runs it and, on success,
records an audit-trail entry describing the change.
"""
from __future__ import annotations

SNMP_VERSIONS = {"2c", "3"}
SNMP_V3_LEVELS = {"noAuthNoPriv", "authNoPriv", "authPriv"}
# Reasonable, permissive protocol name sets (upper-cased before compare).
SNMP_AUTH_PROTOS = {"MD5", "SHA", "SHA-224", "SHA-256", "SHA-384", "SHA-512"}
SNMP_PRIV_PROTOS = {"DES", "AES", "AES-128", "AES-192", "AES-256"}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_snmp(snmp: dict, errors: list[str]) -> None:
    if not isinstance(snmp, dict):
        errors.append("snmp: expected an object")
        return
    if "version" in snmp and str(snmp["version"]) not in SNMP_VERSIONS:
        errors.append(f"snmp.version must be one of {sorted(SNMP_VERSIONS)}")
    for field in ("timeout", "retries"):
        if field in snmp:
            val = snmp[field]
            if not _is_number(val) or val < 0 or val > 60:
                errors.append(f"snmp.{field} must be a number between 0 and 60")
    v3 = snmp.get("v3")
    if v3 is not None:
        if not isinstance(v3, dict):
            errors.append("snmp.v3: expected an object")
        else:
            if v3.get("level") and v3["level"] not in SNMP_V3_LEVELS:
                errors.append(f"snmp.v3.level must be one of {sorted(SNMP_V3_LEVELS)}")
            if v3.get("auth_proto") and str(v3["auth_proto"]).upper() not in SNMP_AUTH_PROTOS:
                errors.append(f"snmp.v3.auth_proto must be one of {sorted(SNMP_AUTH_PROTOS)}")
            if v3.get("priv_proto") and str(v3["priv_proto"]).upper() not in SNMP_PRIV_PROTOS:
                errors.append(f"snmp.v3.priv_proto must be one of {sorted(SNMP_PRIV_PROTOS)}")
            # authPriv needs both keys; authNoPriv needs the auth key. Blank keys
            # are allowed on update (means "leave unchanged"), so only validate
            # the level/user shape here, not key presence.
            if v3.get("user") is not None and not isinstance(v3["user"], str):
                errors.append("snmp.v3.user must be a string")


def _validate_metrics(metrics: dict, errors: list[str]) -> None:
    if not isinstance(metrics, dict):
        errors.append("metrics: expected an object")
        return
    if "enabled" in metrics and not isinstance(metrics["enabled"], bool):
        errors.append("metrics.enabled must be true or false")
    if "token" in metrics:
        token = metrics["token"]
        if not isinstance(token, str):
            errors.append("metrics.token must be a string")
        elif len(token) > 512:
            errors.append("metrics.token is too long (max 512 chars)")
        elif token and any(c.isspace() for c in token):
            errors.append("metrics.token must not contain whitespace")


def _validate_interface_overrides(overrides: dict, errors: list[str]) -> None:
    if not isinstance(overrides, dict):
        errors.append("interface_overrides: expected an object")
        return
    for iface, cfg in overrides.items():
        if not isinstance(cfg, dict):
            errors.append(f"interface_overrides.{iface}: expected an object")
            continue
        if "capture_allowed" in cfg and not isinstance(cfg["capture_allowed"], bool):
            errors.append(f"interface_overrides.{iface}.capture_allowed must be true or false")


def _validate_approved_scope(scope, errors: list[str]) -> None:
    if not isinstance(scope, list):
        errors.append("approved_scope: expected a list")
        return
    for i, entry in enumerate(scope):
        if not isinstance(entry, (str, dict)):
            errors.append(f"approved_scope[{i}] must be a string or object")


def _validate_dangerous_actions(da: dict, errors: list[str]) -> None:
    if not isinstance(da, dict):
        errors.append("dangerous_actions: expected an object")
        return
    if "enabled" in da and not isinstance(da["enabled"], bool):
        errors.append("dangerous_actions.enabled must be true or false")
    ack = da.get("acknowledged")
    if ack is not None:
        if not isinstance(ack, dict):
            errors.append("dangerous_actions.acknowledged must be an object")
        else:
            for key, val in ack.items():
                if not isinstance(val, bool):
                    errors.append(
                        f"dangerous_actions.acknowledged.{key} must be true or false")


ALERT_MIN_STATES = {"spike", "rising", "degraded"}


def _validate_alerting(alerting: dict, errors: list[str]) -> None:
    if not isinstance(alerting, dict):
        errors.append("alerting: expected an object")
        return
    if "enabled" in alerting and not isinstance(alerting["enabled"], bool):
        errors.append("alerting.enabled must be true or false")
    if alerting.get("min_state") and alerting["min_state"] not in ALERT_MIN_STATES:
        errors.append(f"alerting.min_state must be one of {sorted(ALERT_MIN_STATES)}")
    for field, lo, hi in (("poll_seconds", 10, 3600), ("window_minutes", 5, 1440)):
        if field in alerting:
            val = alerting[field]
            if not _is_number(val) or val < lo or val > hi:
                errors.append(f"alerting.{field} must be a number between {lo} and {hi}")
    signals = alerting.get("signals")
    if signals is not None:
        if not isinstance(signals, dict):
            errors.append("alerting.signals must be an object")
        else:
            for key, val in signals.items():
                if not isinstance(val, bool):
                    errors.append(f"alerting.signals.{key} must be true or false")
    webhook = alerting.get("webhook")
    if webhook is not None:
        if not isinstance(webhook, dict):
            errors.append("alerting.webhook must be an object")
        else:
            if "enabled" in webhook and not isinstance(webhook["enabled"], bool):
                errors.append("alerting.webhook.enabled must be true or false")
            url = webhook.get("url")
            if url:
                if not isinstance(url, str):
                    errors.append("alerting.webhook.url must be a string")
                elif not (url.startswith("http://") or url.startswith("https://")):
                    errors.append("alerting.webhook.url must start with http:// or https://")
                elif len(url) > 2048:
                    errors.append("alerting.webhook.url is too long (max 2048 chars)")
    email = alerting.get("email")
    if email is not None:
        if not isinstance(email, dict):
            errors.append("alerting.email must be an object")
        else:
            if "enabled" in email and not isinstance(email["enabled"], bool):
                errors.append("alerting.email.enabled must be true or false")
            if "use_tls" in email and not isinstance(email["use_tls"], bool):
                errors.append("alerting.email.use_tls must be true or false")
            if "smtp_port" in email:
                port = email["smtp_port"]
                if not _is_number(port) or port < 1 or port > 65535:
                    errors.append("alerting.email.smtp_port must be a port between 1 and 65535")
            for field in ("smtp_host", "from_addr", "to_addrs", "username"):
                if field in email and not isinstance(email[field], str):
                    errors.append(f"alerting.email.{field} must be a string")


_VALIDATORS = {
    "snmp": _validate_snmp,
    "metrics": _validate_metrics,
    "interface_overrides": _validate_interface_overrides,
    "approved_scope": _validate_approved_scope,
    "dangerous_actions": _validate_dangerous_actions,
    "alerting": _validate_alerting,
}


def validate_settings(update: dict) -> list[str]:
    """Return a list of validation errors for a partial settings update (empty
    list == valid). Only sections present in `update` are checked."""
    if not isinstance(update, dict):
        return ["settings update must be a JSON object"]
    errors: list[str] = []
    for section, validator in _VALIDATORS.items():
        if section in update:
            validator(update[section], errors)
    return errors


def summarize_settings(update: dict) -> str:
    """A short, secret-free description of which sections/keys changed, for the
    audit trail. Secret leaf values are represented as '<set>'/'<cleared>',
    never their content."""
    secret_leaves = {"community", "auth_key", "priv_key", "token"}
    parts: list[str] = []
    for section, value in (update or {}).items():
        if isinstance(value, dict):
            keys = []
            for k, v in value.items():
                if k in secret_leaves:
                    keys.append(f"{k}={'<set>' if v else '<cleared>'}")
                elif isinstance(v, dict):
                    keys.append(f"{k}={{{','.join(v.keys())}}}")
                else:
                    keys.append(k)
            parts.append(f"{section}({', '.join(keys)})")
        else:
            parts.append(section)
    return "; ".join(parts) or "no changes"
