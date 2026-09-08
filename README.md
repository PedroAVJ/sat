# SAT

SAT is the user's program for Mexican tax records and workflows. The Git
repository contains only stable procedures, schemas, CLI behavior, tests, and
agent guidance. Personal records and working positions live in the private
plugin-owned store at `~/Library/Application Support/sat/`.

The CLI imports records with provenance, verifies stored hashes, reads text
records, extracts installment schedules from SAT payment PDFs, and finds the
next scheduled installment without claiming that it is unpaid.

```bash
sat --json doctor
sat --json store path
sat --json records list
sat --json records verify
sat --json installments extract --year 2025
sat --json installments list --year 2025
sat --json installments next --year 2025
```

Set `SAT_STORE_ROOT` only for testing or an intentional store migration. The
CLI never stores credentials and does not submit declarations, issue CFDIs, or
make payments.
