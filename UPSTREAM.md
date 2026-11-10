# Upstream lineage and safe release process

- Parent repository: [thechrisfischer/reclaim-mcp-server](https://github.com/thechrisfischer/reclaim-mcp-server), `main` at `f38cc8280fee8d9db26410410e722c33653f5a05` (72 tools).
- Original project: [universalamateur/reclaim-mcp-server](https://github.com/universalamateur/reclaim-mcp-server).
- The original Docker Hub `universalamateur/reclaim-mcp-server:latest` returned 49 tools in the initial isolated comparison, despite the extended source providing 72.
- GitHub Actions builds from source and publishes `ghcr.io/godsquantum/cloud9-reclaim-mcp:latest` only when the 72-tool contract passes.
- Never include deployment Compose files, `.env`, credentials, private URLs, calendar payloads, or production logs in this public repository.

## Updating source

1. Inspect the parent fork's commits, and separately changes in the original `universalamateur` project.
2. Bring upstream changes into a temporary feature branch; do not silently overwrite the 23 extra tools.
3. Run `tests/contract-tools.json` against the **built runtime image**, with `RECLAIM_TOOL_PROFILE=full`; every name and full input schema must match.
4. Run upstream unit tests and a local synthetic MCP handshake/extension smoke test.
5. Merge only after review; a push to `main` builds and publishes GHCR via CI.
6. On production servers, pull and redeploy only the Reclaim container after health and client `tools/list` confirmation. Keep the previous immutable digest for rollback.

To intentionally change the tool contract, record the difference in release notes and get a reviewed test update; never update the JSON merely to make CI green.
