# Repository guidance

- This repository is the canonical source for the `sat` plugin.
- SAT is its own institutional domain. Do not move its records or behavior into Near, a bank plugin, or Exocortex.
- Keep the Codex and Claude manifests synchronized.
- Keep all personal RFC data, declarations, CFDIs, receipts, tax records, credentials, secrets, and authored personal tax positions out of Git and out of plugin packages.
- Private content lives under `~/Library/Application Support/sat`; access it through the `sat` CLI so provenance and hashes remain intact.
- Marketplace catalogs may reference this repository after a release; never copy runtime behavior into a catalog repository.
- Bump manifests and package versions together for releases and run `npm test` before publishing.
