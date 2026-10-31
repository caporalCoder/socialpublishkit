# SocialPublishKit

One video. Four destinations. Python, JavaScript, Rust.

Publish MP4 videos through official platform APIs. The Python SDK includes the adapters and a
local gateway. JavaScript/TypeScript and Rust connect to that gateway. No publishing subscription
or Algovid installation required. Bring your own developer apps, accounts and approved permissions.

| Destination | Support |
| --- | --- |
| Facebook Pages | Video Reels. Personal profiles unsupported |
| Instagram professional accounts | Reels through Instagram Unified Login |
| TikTok | Draft uploads. Direct posting subject to app approval and user consent |
| YouTube | Video uploads. Visibility and Shorts eligibility remain platform-controlled |

Version **0.1.1** is available on [PyPI](https://pypi.org/project/socialpublishkit/),
[npm](https://www.npmjs.com/package/socialpublishkit), and [crates.io](https://crates.io/crates/socialpublishkit).
[Release notes and archives](https://github.com/caporalCoder/socialpublishkit/releases/tag/v0.1.1).

## Install

Package name: `socialpublishkit` in all three ecosystems:

```sh
pip install socialpublishkit
npm install socialpublishkit
cargo add socialpublishkit
```

JavaScript and Rust require the Python gateway running on your host. Provider credentials and
app approval are still required. Downloadable archives can also be installed locally with pip,
npm, or a Cargo path dependency.

## Get started from source

```sh
git clone https://github.com/caporalCoder/socialpublishkit.git
cd socialpublishkit
python3 -m venv .venv
source .venv/bin/activate
pip install .
cp examples/gateway.json gateway.local.json
```

Configure your account in `gateway.local.json`, set its credential environment variables, then
start the gateway. [Setup, token refresh and OAuth →](https://github.com/caporalCoder/socialpublishkit/blob/main/docs/usage.md#start-the-local-gateway)

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

JavaScript client:

```js
import { SocialClient } from 'socialpublishkit';
const client = new SocialClient({ token: process.env.SOCIALPUBLISHKIT_TOKEN });
console.log(await client.accounts());
```

Rust dependency:

```toml
socialpublishkit = "0.1.1"
```

[Publishing examples in all three languages →](https://github.com/caporalCoder/socialpublishkit/blob/main/docs/usage.md)

## Behavior

- Durable job receipts and duplicate protection for identical publication IDs.
- No automatic repost after an ambiguous result. Query the receipt and check the destination.
- Credentials stay in the Python host. Clients receive account IDs and publication status.
- The gateway binds to localhost, requires authentication and accepts videos up to 32 MiB.
- No hosted service, scheduler or platform-review bypass. See [limits](https://github.com/caporalCoder/socialpublishkit/blob/main/docs/usage.md#scope-and-limits-of-this-version).

Python 3.10+, Node.js 20+, Rust 1.98.0 tested. The gateway supports macOS/Linux.
Tests use fake providers. Passing tests does not certify app approval or live platform behavior.

## License

[MIT](https://github.com/caporalCoder/socialpublishkit/blob/main/LICENSE). Free to use, modify and redistribute, including commercially, with the copyright
and license notices preserved. Dependencies retain their own licenses.

[Contributing](https://github.com/caporalCoder/socialpublishkit/blob/main/CONTRIBUTING.md) · [Security](https://github.com/caporalCoder/socialpublishkit/blob/main/SECURITY.md)
