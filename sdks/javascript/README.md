# socialpublishkit

Node.js 20+ client for the authenticated local SocialPublishKit gateway. TypeScript declarations
included. Not a browser SDK. Keep the gateway bearer token server-side.

Install: `npm install socialpublishkit`.

```js
import { SocialClient } from 'socialpublishkit';
const client = new SocialClient({ token: process.env.SOCIALPUBLISHKIT_TOKEN });
console.log(await client.accounts());
```

See [docs/usage.md](https://github.com/caporalCoder/socialpublishkit/blob/main/docs/usage.md) in the repository for setup, publishing examples, limits and statuses.
`publish()` returns a job receipt. `publication(id)` returns its current state. Reuse the same
publication ID for identical requests. Do not automatically retry an unknown outcome with a new ID.
TikTok defaults to draft upload and still requires provider approval for public direct posting.

Run `npm test`. MIT licensed (see LICENSE). The npm package name is `socialpublishkit`. Available on [npm](https://www.npmjs.com/package/socialpublishkit).
