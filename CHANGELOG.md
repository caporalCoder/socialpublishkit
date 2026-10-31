# Changelog

## 0.1.1: 2026-10-31

- Block provider HTTP redirects and insecure upload endpoints. redact transport errors.
- Persist refreshed tokens before uploading, including expiry-only and scope-only changes.
- Treat malformed provider success responses as unknown outcomes, never safe-to-retry failures.
- Require stable destination IDs in the gateway. reject duplicate aliases for the same account.
- Bound simultaneous gateway connections and reject submissions during shutdown.
- Add YouTube visibility and audience options in Python, JavaScript/TypeScript and Rust.
  YouTube now defaults to private. category and language are optional.
- Add concurrency, failure-recovery, credential-redaction and package-installation checks.
- Add TypeScript declaration checking and registry package validation to CI.

## 0.1.0: 2026-10-31

- Initial source release: Python adapters, authenticated local gateway, JavaScript and Rust clients.
- Facebook Page and Instagram Reels, TikTok drafts/direct posting, and YouTube uploads.
- Durable publication IDs, duplicate suppression and explicit unknown outcomes.
- MIT license.
