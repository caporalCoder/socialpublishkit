"""Load a portable gateway configuration with credentials referenced by environment name."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from . import Account, Platform, Publisher


def load_config(path: Path, state_dir: Path):
    """Load accounts and persist rotated credentials in a private local file.

    A changed source environment token or account configuration invalidates its cached
    token. No environment values are ever written to logs or included in error messages.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {"app", "app_env", "accounts"}:
        raise ValueError("Configuration requires app/app_env and accounts fields only.")
    app = data.get("app", {})
    app_env = data.get("app_env", {})
    if not isinstance(app, dict) or not isinstance(app_env, dict):
        raise ValueError("app and app_env must be objects.")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in app.items()):
        raise ValueError("App configuration keys and values must be strings.")

    def env(name):
        if not isinstance(name, str) or not name or not os.environ.get(name):
            raise ValueError("A required credential environment variable is missing or empty.")
        return os.environ[name]

    config = dict(app)
    config.update({key: env(name) for key, name in app_env.items()})
    entries = data.get("accounts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Configure at least one account.")
    cache_path = state_dir / "rotated-accounts.local.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    if not isinstance(cache, dict):
        raise ValueError("Invalid rotated account cache.")
    accounts, fingerprints = {}, {}
    allowed = {"id", "platform", "account_id", "name", "access_token_env", "refresh_token_env", "expires_at", "scopes"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - allowed:
            raise ValueError("Unknown account fields; credentials must use environment references.")
        key = entry.get("id")
        if not isinstance(key, str) or not key or key in accounts:
            raise ValueError("Each account needs a unique nonempty id.")
        try:
            platform = Platform(entry.get("platform"))
        except (TypeError, ValueError):
            raise ValueError("Unsupported account platform.") from None
        scopes = entry.get("scopes", [])
        if not isinstance(scopes, list) or any(not isinstance(s, str) for s in scopes):
            raise ValueError("Account scopes must be an array of strings.")
        source = Account(platform, env(entry.get("access_token_env")), str(entry.get("account_id", "")),
                         str(entry.get("name", key)), env(entry["refresh_token_env"]) if entry.get("refresh_token_env") else None,
                         entry.get("expires_at"), tuple(scopes))
        Publisher._credentials(source)
        fingerprint = hashlib.sha256(json.dumps(asdict(source), sort_keys=True).encode()).hexdigest()
        fingerprints[key] = fingerprint
        cached = cache.get(key, {})
        if isinstance(cached, dict) and cached.get("source_fingerprint") == fingerprint:
            saved = cached["account"]
            restored = Account(**(saved | {"platform": Platform(saved["platform"]), "scopes": tuple(saved["scopes"])}))
            Publisher._credentials(restored)
            if (restored.platform, restored.account_id) != (source.platform, source.account_id):
                raise ValueError("Cached credentials do not match the configured destination.")
            source = restored
        accounts[key] = source
    lock = threading.Lock()

    def persist(account):
        key = next(key for key, value in accounts.items() if value is account)
        with lock:
            state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            cache[key] = {"source_fingerprint": fingerprints[key], "account": asdict(account)}
            with tempfile.NamedTemporaryFile(mode="w", dir=state_dir, prefix="credentials-", delete=False) as stream:
                temp = Path(stream.name)
                try:
                    json.dump(cache, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                except BaseException:
                    temp.unlink(missing_ok=True)
                    raise
            try:
                os.replace(temp, cache_path)
            finally:
                temp.unlink(missing_ok=True)

    return Publisher(config, on_account_update=persist), accounts
