# Contributing

Issues and pull requests are welcome. Open an issue for a large API change before implementing it.
Keep platform-specific logic in the Python adapters and the gateway contract consistent across SDKs.

Run the checks listed in [the usage guide](docs/usage.md#verification). Tests must use fake providers,
never real tokens or live social accounts. Add regression tests for upload/retry/status behavior.
Do not commit `.env`, credentials, videos, generated build directories, or personal account data.

By contributing, you agree that your contributions are distributed under the repository's MIT license.
This is a community project with no guaranteed support or response time.
