# Security and privacy

This is a private self-hosted app. All record / configuration endpoints require its Token or an authenticated same-origin session. Cross-origin API clients must send a Bearer token; cross-origin credentialed cookies are not enabled.

The default bind address is 0.0.0.0. Use --host 127.0.0.1 for local-only access. HTTP does not encrypt traffic; use HTTPS for public access. Upstream ActivityWatch authentication must remain enabled when exposed over a public relay.

Never commit state directories, databases, screenshots of real records, runtime logs, access-token, sync-config.json, or frp configuration containing real secrets. Public examples contain placeholders only.

Do not post exploitable vulnerabilities together with real endpoints / credentials in a public issue. Contact the repository maintainer privately when a public repository is created. No private reporting address has been configured yet.
