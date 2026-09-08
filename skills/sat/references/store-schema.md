# Private store schema

The default root is `~/Library/Application Support/sat`. `SAT_STORE_ROOT` may
override it for tests or an intentional migration.

```text
sat/
├── index.json
├── records/
│   └── <kind>/<filename>
└── derived/
    └── installments/<year>.{json,csv,md}
```

`index.json` uses schema version 1. Each record has a stable lower-case ID,
kind, role (`official`, `derived`, or `authored`), store-relative path, SHA-256,
byte length, import timestamp, and optional source repository provenance.

The store root and its directories use owner-only permissions. Imported files
and the manifest use mode `0600`. Import copies are atomic and verified before
the manifest changes. `records verify` recomputes every stored SHA-256. An
explicit `records rehash-authored` revision retains the prior hash in
`revision_history`; official and derived records cannot use that command.

Kinds include `tax-identity`, `annual-returns/2025`,
`tax-installments/2025`, `cfdi-examples/j2`, `working-notes`, and
`legacy-derived/2025`.

No store content belongs in Git, marketplace catalogs, plugin caches, Near, or
a bank-owned data store.
