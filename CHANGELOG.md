# Changelog

## Unreleased

- Use explicit UTF-8 for private JSON, export snapshots, tokens and the login page on Windows.
- Close SQLite fixture connections before removing test databases on Windows.
- Let all CI matrix jobs finish even when another platform fails.

## 0.1.0 — 2026-11-12

Initial source release preparation. Local dashboard, optional MIT Apple archiver, configurable ActivityWatch sources (LAN / frpc), shared / per-source scheduling, token-protected snapshot JSON export, installation and phone-side frpc guides.

No Android collector APK or ADB integration is included. The release is self-hosted and contains no user records or credentials.
