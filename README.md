# SocialPublishKit

One video. Four destinations. Python, JavaScript, Rust.

Publish MP4 videos through official platform APIs. The Python SDK includes the adapters and a
local gateway; JavaScript/TypeScript and Rust connect to that gateway. No publishing subscription
or Algovid installation required. Bring your own developer apps, accounts and approved permissions.

| Destination | Support |
| --- | --- |
| Facebook Pages | Video Reels; personal profiles unsupported |
| Instagram professional accounts | Reels through Instagram Unified Login |
| TikTok | Draft uploads; direct posting subject to app approval and user consent |
| YouTube | Video uploads; visibility and Shorts eligibility remain platform-controlled |

Version **0.1.0** — install from source. Not yet published to PyPI, npm or crates.io.

## Get started

```sh
git clone https://github.com/caporalCoder/socialpublishkit.git
cd socialpublishkit
python3 -m venv .venv
source .venv/bin/activate
pip install .
cp examples/gateway.json gateway.local.json
```

Configure your account in `gateway.local.json`, set its credential environment variables, then
start the gateway. [Setup, token refresh and OAuth →](docs/usage.md#start-the-local-gateway)

```sh
export SOCIALPUBLISHKIT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m socialpublishkit --config gateway.local.json
```

Python client:

```python
import os
from socialpublishkit import GatewayClient

client = GatewayClient(os.environ["SOCIALPUBLISHKIT_TOKEN"])
print(client.accounts())
```

JavaScript client (install with `npm install /path/to/socialpublishkit/sdks/javascript`):

```js
import { SocialClient } from 'socialpublishkit';
const client = new SocialClient({ token: process.env.SOCIALPUBLISHKIT_TOKEN });
console.log(await client.accounts());
```

Rust dependency:

```toml
socialpublishkit = { git = "https://github.com/caporalCoder/socialpublishkit.git", tag = "v0.1.0" }
```

[Publishing examples in all three languages →](docs/usage.md)

## Behavior

- Durable job receipts and duplicate protection for identical publication IDs.
- No automatic repost after an ambiguous result. Query the receipt and check the destination.
- Credentials stay in the Python host. Clients receive account IDs and publication status.
- The gateway binds to localhost, requires authentication and accepts videos up to 32 MiB.
- No hosted service, scheduler or platform-review bypass. See [limits](docs/usage.md#scope-and-limits-of-this-version).

Python 3.10+, Node.js 20+, Rust 1.98.0 tested. The gateway supports macOS/Linux.
Tests use fake providers; passing tests does not certify app approval or live platform behavior.

## License

[MIT](LICENSE). Free to use, modify and redistribute, including commercially, with the copyright
and license notices preserved. Dependencies retain their own licenses.

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
