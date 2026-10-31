"""Start the local SocialPublishKit gateway from your config or existing Algovid accounts."""

import argparse
import os
from pathlib import Path

from . import Account, Platform, Publisher
from .gateway import Gateway
from .providers import Comptes
from .config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="JSON configuration with credential environment references")
    source.add_argument("--algovid-root", type=Path, help="Optional compatibility with an existing Algovid workspace")
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    token = os.environ.get("SOCIALPUBLISHKIT_TOKEN", "")
    if len(token) < 32:
        parser.error("Set SOCIALPUBLISHKIT_TOKEN to a random token of at least 32 characters.")
    if args.config:
        state_dir = (args.state_dir or Path(".state")).expanduser().resolve()
        try:
            publisher, accounts = load_config(args.config.expanduser().resolve(), state_dir)
        except (ValueError, OSError, TypeError, KeyError):
            parser.error("Invalid configuration or credentials. Check the example config and required environment variables.")
    else:
        root = args.algovid_root.expanduser().resolve()
        state_dir = (args.state_dir or root / "runs" / "social-sdk").expanduser().resolve()
        publisher, accounts = from_algovid(root)
    if not accounts:
        parser.error("No connected accounts. Configure credentials or connect them in Algovid first.")
    gateway = Gateway(publisher, accounts, token=token, state_dir=state_dir)
    try:
        server = gateway.server(args.port)
        print(f"SocialPublishKit: http://127.0.0.1:{server.server_port} (authenticated; {len(accounts)} accounts)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        gateway.close()


def from_algovid(root):
    store = Comptes(str(root))
    config = {}
    for provider in store.reseaux.values():
        for key in (*provider.variables, "TIKTOK_SCOPES", "META_PAGE_ID", "INSTAGRAM_ACCOUNT_ID"):
            config[key] = provider.valeur(key)
    accounts = {}
    for key, data in store.lire().items():
        if key not in store.reseaux:
            continue
        platform = Platform.FACEBOOK_PAGE if key == "facebook" else Platform(key)
        target = data.get("page") or data.get("ig") or data.get("open_id") or data.get("channel_id") or ""
        accounts[key] = Account(platform, data["jeton"], target, data.get("nom", ""),
                                data.get("renouvellement"), data.get("expire"),
                                tuple(filter(None, data.get("scope", "").split(","))))

    def persist(account):
        key = "facebook" if account.platform == Platform.FACEBOOK_PAGE else account.platform.value
        latest = store.lire().get(key)
        if latest is None:
            raise RuntimeError("Account disconnected while publishing.")
        latest.update(jeton=account.access_token, renouvellement=account.refresh_token,
                      expire=account.expires_at, scope=",".join(account.scopes))
        store.enregistrer({key: latest})

    return Publisher(config, on_account_update=persist), accounts


if __name__ == "__main__":
    main()
