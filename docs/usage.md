# SocialPublishKit SDK: 0.1.1

Publish MP4 videos using official APIs for Facebook **Pages**, Instagram professional accounts,
TikTok and YouTube. The Python package works directly. Node.js and Rust call the same local Python
gateway. See [GitHub Releases](https://github.com/caporalCoder/socialpublishkit/releases) for
registry availability and downloadable release archives.
The JavaScript and Rust packages are gateway clients, not independent native platform adapters.

No Buffer or other hosted publishing subscription is required. Running on your own Mac avoids
hosting fees. You still supply developer applications, approved permissions, connected accounts,
and the computer that runs the gateway. Platform quotas and review restrictions still apply.
There is no public hosted service bundled here. SocialPublishKit is open source under the
[MIT license](../LICENSE), including commercial use and redistribution with notices preserved.

| Destination | Current adapter | Important boundary |
| --- | --- | --- |
| Facebook Page | Local video → Reel | Personal profiles, including professional-mode profiles, are unsupported |
| Instagram | Reel via existing Unified Login integration | Professional account in a Meta business portfolio. No Facebook Page required by this integration |
| TikTok | Inbox draft. Direct private/public posting when authorized | Default is a draft, requiring completion in TikTok. SDK does not unlock app approval |
| YouTube | Resumable video upload | An upload is not proof of processing, public visibility, or Shorts classification |

## Install

Python 3.10+. No runtime dependencies and no Manim/Claude/rendering dependencies:

```sh
python3 -m venv /tmp/socialpublishkit-env
/tmp/socialpublishkit-env/bin/pip install /path/to/socialpublishkit
```

Node.js 20+ (includes TypeScript declarations. No runtime dependencies):

```sh
npm install /path/to/socialpublishkit/sdks/javascript
```

Rust: add a path dependency to the consuming application's Cargo.toml:

```toml
[dependencies]
socialpublishkit = { path = "/path/to/socialpublishkit/sdks/rust" }
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
```

The Rust crate is tested with the repository-pinned Rust 1.98.0 toolchain. It uses reqwest,
serde, base64 and Tokio. The optional gateway currently targets macOS/Linux (uses `flock`).
The SDK clients themselves do not depend on a desktop browser or UI automation.

## Start the local gateway

Copy [examples/gateway.json](../examples/gateway.json) to `gateway.local.json`. Each account has
an `id`, `platform`, `account_id`, `name`, `scopes`, and an `access_token_env` naming an environment
variable. Supported platforms are `facebook_page`, `instagram`, `tiktok`, and `youtube`.
Every gateway account needs its provider account ID (TikTok `open_id`, YouTube channel ID,
or numeric Facebook Page/Instagram ID). Configure each destination only once. Obtain tokens using your approved app's
OAuth flow. The example contains no credentials. Set `TIKTOK_ACCESS_TOKEN` in your environment
using your secret manager before running the example.

```sh
# Keep this private; give the same value to the SDK process through its environment.
export SOCIALPUBLISHKIT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m socialpublishkit --config gateway.local.json --state-dir .state --port 8787
```

Use `app` for nonsecret provider configuration, and `app_env` to map provider settings such as
`GOOGLE_CLIENT_SECRET` to environment variable names. See the OAuth configuration table below.
For refreshable accounts, set `refresh_token_env` and the current `expires_at` Unix timestamp,
as well as the provider's app credentials. Omitted expiry means the token is treated as unexpired.

Rotated credentials are persisted in `.state/rotated-accounts.local.json` with file mode 600.
Keep the state directory private and persistent across restarts. The cache is invalidated for an
account if its source token or configuration changes. This file is not encrypted: protect it as a
secret, exclude it from backups you do not trust, and never commit it. Disconnect an account by
removing its configuration and restarting. Remove its cached credentials when no longer needed.

The gateway binds only to `127.0.0.1:8787`, requires a bearer token on every route, and rejects
browser-origin requests. Never embed its token in a website or frontend bundle. HTTPS remote URLs
in clients require a separately secured deployment. This project does not expose one.

Receipts live in `.state/publications.sqlite3` (mode 600). Incoming videos are placed in a private
temporary directory and removed after the attempt. After an abrupt kill, leftover `upload-*`
directories may need local cleanup. Receipts contain hashes, safe results and generic errors,
not provider tokens, captions or video bytes. Use one gateway per state directory.

### Optional Algovid compatibility

Existing Algovid users can instead run:

```sh
python -m socialpublishkit --algovid-root /path/to/algovid
```

This reads connected accounts and app settings from Algovid and saves refreshed tokens back to
its store. Receipts default to `runs/social-sdk/`. Restart after account/configuration changes.
Do not publish simultaneously through Studio and the SDK for the same account: their refreshes
and queues are not coordinated. Algovid is not required for the standalone configuration above.

## Python through the gateway

```python
import os
from socialpublishkit import GatewayClient, TikTokOptions

client = GatewayClient(os.environ["SOCIALPUBLISHKIT_TOKEN"])
print(client.accounts())  # safe IDs/names; no provider tokens

job = client.publish(
    publication_id="quicksort-tiktok-v1",  # persist this ID; reuse for an identical retry
    account="my-tiktok",                  # ID from your configuration / accounts()
    video="/absolute/path/video.mp4",
    caption="Tri rapide expliqué. #CodeExample",
    tiktok=TikTokOptions(mode="draft"),
)
print(job)
print(client.publication(job["id"]))
```

## JavaScript / TypeScript

```js
import { SocialClient } from 'socialpublishkit';

const client = new SocialClient({ token: process.env.SOCIALPUBLISHKIT_TOKEN });
console.log(await client.accounts());
const job = await client.publish({
  publicationId: 'quicksort-tiktok-v1',
  account: 'my-tiktok',
  video: '/absolute/path/video.mp4',
  caption: 'Tri rapide expliqué. #CodeExample',
  tiktok: { mode: 'draft' },
});
console.log(await client.publication(job.id));
```

## Rust

```rust
use socialpublishkit::{SocialClient, PublishRequest, TikTokOptions};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = SocialClient::new(
        "http://127.0.0.1:8787", std::env::var("SOCIALPUBLISHKIT_TOKEN")?
    )?;
    println!("{:?}", client.accounts().await?);
    let job = client.publish(&PublishRequest {
        publication_id: "quicksort-tiktok-v1".into(),
        account: "my-tiktok".into(),
        video: "/absolute/path/video.mp4".into(),
        caption: "Tri rapide expliqué. #CodeExample".into(),
        tiktok: Some(TikTokOptions::default()),
        ..Default::default()
    }).await?;
    println!("{:?}", client.publication(&job.id).await?);
    Ok(())
}
```

Select an account ID returned by `accounts()` to use another configured destination. Omit TikTok options for those destinations. Include `title` and `tags`
for YouTube. Reuse the same ID across languages only for the **exact same JSON request**. Optional
field defaults can differ, so use one client for retries of a job, or use GET to retrieve it.

## YouTube visibility and audience

YouTube uploads default to **private**. Choose visibility and the correct audience explicitly;
category and language are optional and are no longer hard-coded to French education videos.

```python
from socialpublishkit import YouTubeOptions
# Pass alongside your existing publish() arguments:
options = YouTubeOptions(privacy="public", made_for_kids=False, category_id="27", language="fr")
# client.publish(..., youtube=options)
```

JavaScript uses `youtube: { privacy: 'public', made_for_kids: false }`.
Rust uses `youtube: Some(YouTubeOptions { privacy: YouTubePrivacy::Public, ..Default::default() })`.
The provider may restrict public visibility regardless of the requested setting.

## Direct Python publishing and OAuth

The direct client does not need the gateway or Algovid, but it also has no persistent job ledger:

```python
import os
from socialpublishkit import Account, Platform, Publisher, VideoPost

publisher = Publisher()  # explicit configuration only; no implicit .env lookup
account = Account(
    platform=Platform.FACEBOOK_PAGE,
    account_id=os.environ["FACEBOOK_PAGE_ID"],
    access_token=os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"],
)
result = publisher.publish(account, VideoPost(
    video="/absolute/path/video.mp4", caption="Tri rapide expliqué. #CodeExample"
))
print(result.status, result.url)
```

For OAuth, pass app configuration in `Publisher(config={...}, on_account_update=save_account)`.
The optional callback persists connected/rotated credentials to **your secure server-side store**.
The mutable Account is also updated in place. Never log/serialize it into a frontend response.

| Platform | Configuration |
| --- | --- |
| Facebook Page | `META_APP_ID`, `META_APP_SECRET`. Optional `META_PAGE_ID` to choose one authorized Page |
| Instagram | `META_APP_ID`, `META_APP_SECRET`, `INSTAGRAM_CONFIG_ID`. Optional `INSTAGRAM_ACCOUNT_ID` |
| TikTok | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, optional `TIKTOK_SCOPES` (default `user.info.basic,video.upload`) |
| YouTube | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |

1. Generate a cryptographically random one-use state and store it with the user's session.
2. Call `authorization_url(platform, state=state, redirect_uri=registered_callback)`.
3. In your callback, handle denial and **verify and consume state before exchanging the code**.
4. Call `exchange_code(platform, code=code, redirect_uri=registered_callback)`. Securely store the Account.

The SDK does not host OAuth callbacks or verify application-session state for you. Never accept
an arbitrary callback destination from a browser request. Multiple Meta accounts require explicit
selection. No arbitrary first Page is chosen. JS/Rust use accounts connected through the gateway
host. They do not handle provider access tokens themselves.

## Results, failures and duplicate protection

`publish()` on gateway clients returns a job receipt, usually `state="processing"`, not a public
post. Poll `publication(id)` until it has a terminal state. Polling does not send another video.

| Job state | Meaning |
| --- | --- |
| `processing` | Queued or in progress |
| `completed` | A provider result was recorded. Inspect `result.status` |
| `failed` | Request was rejected before upload. Fix the request before creating a new ID |
| `unknown` | Outcome unconfirmed. Check the destination manually before any new attempt |

Provider result statuses: `draft_delivered` means TikTok inbox delivery, `uploaded` means YouTube
accepted the upload, `published` means the provider reported completion. Completion does not
guarantee public visibility or the absence of later moderation. A result may not include a URL.

The gateway commits the request ID before enqueueing. Identical repeats return the existing job;
changed request bodies or destination IDs return HTTP 409. Interrupted jobs become `unknown`
on restart. Clients do not automatically retry requests or follow redirects. After a connection
failure, query the same ID. If the request never reached the service (404), retry using that same ID.
Never generate a new ID merely because a request timed out. This is protection per request ID,
not global detection of the same video under different IDs or publication through Studio/browser.

The direct Python client raises `ValidationError` before an upload for invalid local input, or
`PublishingError` with `outcome_unknown=True` when a publish attempt lacks a confirmed result.
It deliberately hides provider exception bodies that could contain tokens. No automatic retry.

## TikTok direct posting and AI disclosure

Direct posting still requires approved `video.publish`, user authorization, and TikTok's required
app audit for public visibility. Changing SDK configuration does not grant those permissions.

For an authorized direct-post integration, fetch `publisher.tiktok_creator_info(account)` and show
the creator identity, current privacy choices, interaction controls, and disclosure controls in
your host application's consent UI. Pass the user's choices explicitly. Include the real video
`duration_seconds`. The adapter rechecks allowed privacy/duration/interaction limits before upload.
This library is not a ready-made TikTok-reviewed consent UI.

`TikTokOptions(mode="public", duration_seconds=24.2, ai_generated=False)` explicitly leaves the
creator AI label off. `ai_generated=True` explicitly adds it. Default `None` omits the flag.
AI-assisted coding does **not** set this flag automatically. Draft upload cannot set the final
caption or disclosure controls: the user completes those in TikTok.

## Scope and limits of this version

- MP4 video only. No photo/carousel, text-only post, analytics, deletion or moderation endpoints.
- Gateway uploads are capped at **32 MiB** and sent as base64 JSON. Choose multipart/streaming
  for a future large-file version. Direct adapters buffer some platform uploads in memory.
- Immediate execution, up to eight queued/in-progress gateway jobs, one worker per account;
  durable future scheduling is not included. The gateway does not resume interrupted uploads.
- Token encryption/keychain storage, multi-tenant hosting and a reviewed OAuth UI are not included.
- API version compatibility and third-party account approval must be verified before wider release.
- No live posts are created by the SDK tests. A new live SDK publication still needs an intentional test.

## Verification

From the repository root:

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
npm --prefix sdks/javascript ci
npm --prefix sdks/javascript test
npm --prefix sdks/javascript run typecheck
cargo +1.98.0 test --manifest-path sdks/rust/Cargo.toml --locked
python tests/check_sdk_clients.py
python -m build
python -m twine check --strict dist/*.whl dist/*.tar.gz
python tools/verify_packages.py
```

The cross-language test starts the real gateway with a fake provider and asserts exactly four
provider calls for two clients across TikTok and YouTube, despite repeated requests. It never loads actual account tokens.

Official references: [TikTok Direct Post](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post),
[TikTok approval prerequisites](https://developers.tiktok.com/doc/content-posting-api-get-started),
[Meta Reels](https://developers.facebook.com/docs/video-api/guides/reels-publishing/),
[Instagram Unified Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started/),
[YouTube upload API](https://developers.google.com/youtube/v3/docs/videos/insert).
