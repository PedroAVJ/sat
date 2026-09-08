---
name: sat
description: Manage the user's private Mexican SAT domain through the local SAT store and CLI. Use for RFC or Constancia de Situacion Fiscal lookup, annual declarations, tax installment capture lines, CFDI examples, receipts, tax working notes, record imports, and SAT provenance or integrity checks.
---

# SAT

Use the `sat` CLI as the stable front door. Keep SAT separate from Near and
bank-owned data. The plugin package contains behavior only; personal records,
identifiers, credentials, and authored tax positions live in the private store.

## Start safely

```bash
sat --json doctor
sat --json records verify
```

Stop if the manifest is unreadable or any hash fails. Never print credentials,
attach private records, or send identifiers outside the current task without
the user's explicit confirmation for that exact action.

## Read records

List metadata before opening content:

```bash
sat --json records list
sat --json records get <record-id>
sat --json records read <text-record-id>
```

Use `records read` only when the task needs the private text. Binary records are
resolved with `records get`; read the returned private path with the appropriate
local document tool. Read [references/store-schema.md](references/store-schema.md)
when importing, migrating, or debugging records.

## Answer installment questions

Prefer the generated schedule, then the stored source PDF if a field needs
verification:

```bash
sat --json installments list --year <year>
sat --json installments next --year <year> --as-of YYYY-MM-DD
```

The `next` command is date-based and does not track payment state. Do not call
an installment unpaid without separate payment evidence. If the user requests
payment confirmation, take the exact capture line and amount from SAT, then use
the appropriate bank or email workflow for read-only proof; do not move that
external system's records into SAT.

## Import arrived records

Import through the CLI so each copy is hashed and receives source provenance:

```bash
sat --json records import /private/source.pdf \
  --id stable-record-id \
  --kind annual-returns/2025 \
  --role official \
  --source-repository private-owner/repository \
  --source-revision <commit> \
  --source-path path/in/source.pdf \
  --git-blob <blob-id>
```

Use role `authored` for the user's editable interpretations or decisions and
`derived` for generated views. Never add private store content to the plugin
repository.

After the user or an authorized agent edits an authored record at the private path
returned by `records get`, accept that deliberate revision while retaining the
prior hash:

```bash
sat --json records rehash-authored <record-id>
sat --json records verify
```

Never use this command on official or derived records.

## Rebuild installment views

After importing every installment PDF for a tax year, run:

```bash
sat --json installments extract --year <year>
sat --json records verify
```

Review the extracted rows against source PDFs before relying on a changed
parser. The CLI writes private JSON, CSV, and Markdown views under the store's
`derived/installments/` directory.

## Boundaries

- Do not submit declarations, issue CFDIs, make payments, or mutate external systems unless the user separately and explicitly authorizes the exact action.
- Treat working tax positions as hypotheses until the user's accountant or the relevant authority settles them.
- Do not infer current law from stored notes; verify live legal/tax guidance when a decision depends on it.
- Do not use Near as a SAT record destination and do not make the bank plugin own SAT procedures.
