# socialpublishkit

Node.js 20+ client for the authenticated local SocialPublishKit gateway. TypeScript declarations
included. Not a browser SDK; keep the gateway bearer token server-side.

Install locally: `npm install /path/to/socialpublishkit/sdks/javascript`.

```js
import { SocialClient } from 'socialpublishkit';
const client = new SocialClient({ token: process.env.SOCIALPUBLISHKIT_TOKEN });
console.log(await client.accounts());
```

See [docs/usage.md](https://github.com/caporalCoder/socialpublishkit/blob/main/docs/usage.md) in the repository for setup, publishing examples, limits and statuses.
`publish()` returns a job receipt; `publication(id)` returns its current state. Reuse the same
publication ID for identical requests. Do not automatically retry an unknown outcome with a new ID.
TikTok defaults to draft upload and still requires provider approval for public direct posting.

Run `npm test`. This package is not yet published to npm and is licensed under MIT (see LICENSE).
