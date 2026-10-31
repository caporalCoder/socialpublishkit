# socialpublishkit

Async Rust client for the authenticated local SocialPublishKit gateway. Platform credentials
stay in the Python gateway. The client uses only its bearer token.

Install with `cargo add socialpublishkit`. Requires Rust 1.88+, tested on Rust 1.98.0.
See [docs/usage.md](https://github.com/caporalCoder/socialpublishkit/blob/main/docs/usage.md) in the repository for setup and complete examples.

Methods: `SocialClient::accounts`, `publish(&PublishRequest)`, `publication(id)`.
Publishing returns a job receipt, not a guarantee of public visibility. The default TikTok mode
delivers a draft. Public direct posting still requires TikTok authorization and app approval.
Reuse a stable publication ID and query it after a timeout. Never blindly retry with a new ID.

Run `cargo test` from this directory. MIT licensed (see LICENSE). The crates.io package name is `socialpublishkit`. Available on [crates.io](https://crates.io/crates/socialpublishkit).
