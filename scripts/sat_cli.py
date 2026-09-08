#!/usr/bin/env python3
"""Private local SAT record store and installment CLI."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_STORE_ROOT = Path.home() / "Library/Application Support/sat"


class SatError(RuntimeError):
    pass


def store_root() -> Path:
    override = os.environ.get("SAT_STORE_ROOT")
    return Path(override).expanduser().resolve() if override else DEFAULT_STORE_ROOT


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SatError(f"unsafe relative path: {raw}")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", raw):
        raise SatError(f"unsupported path characters: {raw}")
    return path


def manifest_path(root: Path) -> Path:
    return root / "index.json"


def load_manifest(root: Path, *, create: bool = False) -> dict[str, Any]:
    path = manifest_path(root)
    if not path.exists():
        if create:
            return {"schema_version": SCHEMA_VERSION, "records": []}
        raise SatError(f"SAT store is not initialized: {root}")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SatError(f"cannot read SAT store manifest: {exc}") from exc
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("records"), list):
        raise SatError("unsupported SAT store manifest")
    return payload


def atomic_write(path: Path, content: str) -> None:
    ensure_private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_manifest(root: Path, payload: dict[str, Any]) -> None:
    atomic_write(manifest_path(root), json.dumps(payload, indent=2, sort_keys=True) + "\n")


def initialize_store(root: Path) -> dict[str, Any]:
    ensure_private_dir(root)
    ensure_private_dir(root / "records")
    ensure_private_dir(root / "derived")
    if not manifest_path(root).exists():
        save_manifest(root, {"schema_version": SCHEMA_VERSION, "records": []})
    return load_manifest(root)


def find_record(payload: dict[str, Any], record_id: str) -> dict[str, Any]:
    matches = [record for record in payload["records"] if record["id"] == record_id]
    if not matches:
        raise SatError(f"record not found: {record_id}")
    if len(matches) > 1:
        raise SatError(f"duplicate record id: {record_id}")
    return matches[0]


def import_record(args: argparse.Namespace) -> dict[str, Any]:
    root = store_root()
    payload = initialize_store(root)
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise SatError(f"source is not a file: {source}")
    kind = safe_relative(args.kind).as_posix()
    destination_name = safe_relative(args.destination or source.name)
    destination_relative = Path("records") / kind / destination_name
    destination = root / destination_relative
    record_hash = sha256(source)
    record_id = args.record_id
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", record_id):
        raise SatError("record id must be lower-case hyphen-case")

    existing = next((item for item in payload["records"] if item["id"] == record_id), None)
    if existing:
        if existing["sha256"] == record_hash and (root / existing["relative_path"]).is_file():
            return {"status": "unchanged", "record": existing}
        raise SatError(f"record id already exists with different content: {record_id}")

    ensure_private_dir(destination.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, 0o600)
        if sha256(Path(temporary)) != record_hash:
            raise SatError(f"copy verification failed: {source}")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    record = {
        "id": record_id,
        "kind": kind,
        "role": args.role,
        "relative_path": destination_relative.as_posix(),
        "sha256": record_hash,
        "size_bytes": source.stat().st_size,
        "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": {
            "repository": args.source_repository,
            "revision": args.source_revision,
            "path": args.source_path,
            "git_blob": args.git_blob,
        },
    }
    payload["records"].append(record)
    payload["records"].sort(key=lambda item: item["id"])
    save_manifest(root, payload)
    return {"status": "imported", "record": record}


def list_records(args: argparse.Namespace) -> dict[str, Any]:
    root = store_root()
    records = load_manifest(root)["records"]
    if args.kind:
        records = [record for record in records if record["kind"] == args.kind]
    if args.role:
        records = [record for record in records if record["role"] == args.role]
    return {"store_root": str(root), "count": len(records), "records": records}


def get_record(args: argparse.Namespace) -> dict[str, Any]:
    root = store_root()
    record = find_record(load_manifest(root), args.record_id)
    path = root / record["relative_path"]
    return {"record": record, "path": str(path), "exists": path.is_file()}


def read_record(args: argparse.Namespace) -> dict[str, Any]:
    result = get_record(args)
    path = Path(result["path"])
    if path.suffix.lower() not in {".md", ".txt", ".json", ".csv", ".xml"}:
        raise SatError("record is binary; use `records get` for its private path")
    result["content"] = path.read_text(errors="replace")
    return result


def verify_records(_args: argparse.Namespace) -> dict[str, Any]:
    root = store_root()
    results = []
    valid = True
    for record in load_manifest(root)["records"]:
        path = root / record["relative_path"]
        actual = sha256(path) if path.is_file() else None
        ok = actual == record["sha256"]
        valid = valid and ok
        results.append({"id": record["id"], "ok": ok, "actual_sha256": actual})
    return {"valid": valid, "count": len(results), "records": results}


def rehash_authored_record(args: argparse.Namespace) -> dict[str, Any]:
    root = store_root()
    payload = load_manifest(root)
    record = find_record(payload, args.record_id)
    if record["role"] != "authored":
        raise SatError("only authored records may accept an editable revision")
    path = root / record["relative_path"]
    if not path.is_file():
        raise SatError(f"authored record is missing: {path}")
    current = sha256(path)
    previous = record["sha256"]
    if current == previous:
        return {"status": "unchanged", "record": record}
    record.setdefault("revision_history", []).append({
        "sha256": previous,
        "replaced_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    record["sha256"] = current
    record["size_bytes"] = path.stat().st_size
    record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_manifest(root, payload)
    return {"status": "updated", "record": record}


@dataclass(frozen=True)
class Installment:
    source_record_id: str
    source_file: str
    installment_number: int
    total_installments: int
    declaration_year: int
    rfc: str
    taxpayer_name: str
    operation_number: str
    payment_document_number: str
    tax_concept: str
    amount_due_mxn: float
    balance_before_payment_mxn: float
    balance_after_payment_mxn: float
    valid_until: str
    line_capture: str


def must_match(pattern: str, text: str, *, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    if match is None:
        raise SatError(f"missing expected SAT field: {pattern}")
    return match.group(1)


def parse_money(raw: str) -> float:
    return float(raw.replace(",", "").replace("$", ""))


def iso_date(raw: str) -> str:
    return datetime.strptime(raw, "%d/%m/%Y").strftime("%Y-%m-%d")


def load_pdf_text(path: Path) -> str:
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:
        raise SatError("pdfplumber is required to extract SAT installment PDFs") from exc
    with pdfplumber.open(path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def parse_installment_text(text: str, *, source_record_id: str, source_file: str,
                           installment_number: int, total_installments: int,
                           declaration_year: int) -> Installment:
    rfc = must_match(r"RFC:\s*([A-Z0-9]+)", text)
    taxpayer_name = must_match(r"(?:Nombre|NOMBRE):\s*([A-ZÁÉÍÓÚÑ ]+)", text).strip()
    operation_number = (must_match(r"Número de operación:\s*([0-9]+)", text)
                        if installment_number == 1 else must_match(r"Documento:\s*([0-9]+)", text))
    tax_concept = (must_match(r"Concepto de pago 1:\s*([A-ZÁÉÍÓÚÑ ]+)", text).strip()
                   if installment_number == 1 else "ISR PERSONAS FÍSICAS")
    if installment_number == 1:
        payment_document_number = operation_number
        amount_due = parse_money(must_match(r"Cantidad a pagar:\s*([\d,]+)", text))
        balance_before = parse_money(must_match(r"Cantidad a cargo:\s*([\d,]+)", text))
        balance_after = parse_money(must_match(r"Importe sin la primera parcialidad:\s*([\d,]+)", text))
    else:
        payment_document_number = must_match(r"Número de Documento:\s*([0-9]+)", text)
        pair = must_match(r"Documento:\s*[0-9]+\s+Parcialidad:\s*\d+/\d+\s+\$([\d,]+\s+\$[\d,]+)", text)
        balance_raw, amount_raw = pair.split()
        balance_before = parse_money(balance_raw)
        amount_due = parse_money(amount_raw)
        balance_after = balance_before - amount_due
    valid_until = iso_date(must_match(r"Vigente hasta:\s*(\d{2}/\d{2}/\d{4})", text))
    line_capture = must_match(r"Línea de Importe total\s+([0-9A-Z ]+)\s+\$[\d,]+", text, flags=re.MULTILINE).strip()
    return Installment(source_record_id, source_file, installment_number, total_installments,
                       declaration_year, rfc, taxpayer_name, operation_number,
                       payment_document_number, tax_concept, amount_due, balance_before,
                       balance_after, valid_until, line_capture)


def extract_installments(args: argparse.Namespace) -> dict[str, Any]:
    root = store_root()
    kind = f"tax-installments/{args.year}"
    sources = [record for record in load_manifest(root)["records"]
               if record["kind"] == kind and record["relative_path"].lower().endswith(".pdf")]
    if not sources:
        raise SatError(f"no stored installment PDFs for {args.year}")
    numbered = []
    for record in sources:
        match = re.search(r"parcialidad[-_ ](\d+)", Path(record["relative_path"]).name, re.IGNORECASE)
        if match is None:
            raise SatError(f"cannot determine installment number: {record['relative_path']}")
        numbered.append((int(match.group(1)), record))
    numbered.sort(key=lambda pair: pair[0])
    total = max(number for number, _record in numbered)
    rows = [parse_installment_text(load_pdf_text(root / record["relative_path"]),
            source_record_id=record["id"], source_file=Path(record["relative_path"]).name,
            installment_number=number, total_installments=total, declaration_year=args.year)
            for number, record in numbered]
    serialized = [asdict(row) for row in rows]
    output_dir = root / "derived" / "installments"
    ensure_private_dir(output_dir)
    json_path, csv_path, report_path = (output_dir / f"{args.year}.json",
                                        output_dir / f"{args.year}.csv",
                                        output_dir / f"{args.year}.md")
    atomic_write(json_path, json.dumps(serialized, indent=2, ensure_ascii=False) + "\n")
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(Installment.__dataclass_fields__))
    writer.writeheader()
    writer.writerows(serialized)
    atomic_write(csv_path, buffer.getvalue())
    lines = [f"# {args.year} Tax Installments", "",
             f"- Generated from {len(rows)} verified records in the private SAT store.",
             f"- Total scheduled: `MXN {sum(row.amount_due_mxn for row in rows):,.2f}`",
             "- A schedule is not proof that an installment remains unpaid.", "",
             "| Installment | Amount (MXN) | Balance Before (MXN) | Balance After (MXN) | Valid Until | Line Capture |",
             "| ---: | ---: | ---: | ---: | --- | --- |"]
    for row in rows:
        lines.append(f"| {row.installment_number}/{row.total_installments} | {row.amount_due_mxn:,.2f} | "
                     f"{row.balance_before_payment_mxn:,.2f} | {row.balance_after_payment_mxn:,.2f} | "
                     f"{row.valid_until} | `{row.line_capture}` |")
    atomic_write(report_path, "\n".join(lines) + "\n")
    return {"year": args.year, "count": len(rows),
            "outputs": {"json": str(json_path), "csv": str(csv_path), "report": str(report_path)},
            "rows": serialized}


def load_installment_rows(year: int) -> list[dict[str, Any]]:
    path = store_root() / "derived" / "installments" / f"{year}.json"
    if not path.is_file():
        raise SatError(f"installments for {year} have not been extracted")
    return json.loads(path.read_text())


def list_installments(args: argparse.Namespace) -> dict[str, Any]:
    rows = load_installment_rows(args.year)
    return {"year": args.year, "count": len(rows), "rows": rows, "payment_status": "not tracked"}


def next_installment(args: argparse.Namespace) -> dict[str, Any]:
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    candidates = [row for row in load_installment_rows(args.year)
                  if date.fromisoformat(row["valid_until"]) >= as_of]
    selected = min(candidates, key=lambda row: row["valid_until"]) if candidates else None
    return {"year": args.year, "as_of": as_of.isoformat(), "scheduled_installment": selected,
            "payment_status": "not tracked",
            "caveat": "Date-based schedule lookup only; verify payment separately before treating it as due."}


def doctor(_args: argparse.Namespace) -> dict[str, Any]:
    root = store_root()
    manifest_ok, record_count, error = False, 0, None
    try:
        payload = load_manifest(root)
        manifest_ok, record_count = True, len(payload["records"])
    except SatError as exc:
        error = str(exc)
    try:
        import pdfplumber  # type: ignore  # noqa: F401
        pdfplumber_available = True
    except ImportError:
        pdfplumber_available = False
    return {"store_root": str(root), "store_exists": root.is_dir(), "manifest_ok": manifest_ok,
            "record_count": record_count, "pdfplumber_available": pdfplumber_available, "error": error}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sat")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("doctor")
    command.set_defaults(handler=doctor)
    store = commands.add_parser("store").add_subparsers(dest="store_command", required=True)
    command = store.add_parser("path")
    command.set_defaults(handler=lambda _args: {"store_root": str(store_root())})
    command = store.add_parser("init")
    command.set_defaults(handler=lambda _args: {"store_root": str(store_root()), "manifest": initialize_store(store_root())})
    records = commands.add_parser("records").add_subparsers(dest="records_command", required=True)
    command = records.add_parser("import")
    command.add_argument("source")
    command.add_argument("--id", dest="record_id", required=True)
    command.add_argument("--kind", required=True)
    command.add_argument("--role", choices=["official", "derived", "authored"], default="official")
    command.add_argument("--destination")
    command.add_argument("--source-repository")
    command.add_argument("--source-revision")
    command.add_argument("--source-path")
    command.add_argument("--git-blob")
    command.set_defaults(handler=import_record)
    command = records.add_parser("list")
    command.add_argument("--kind")
    command.add_argument("--role", choices=["official", "derived", "authored"])
    command.set_defaults(handler=list_records)
    for name, handler in (("get", get_record), ("read", read_record)):
        command = records.add_parser(name)
        command.add_argument("record_id")
        command.set_defaults(handler=handler)
    command = records.add_parser("verify")
    command.set_defaults(handler=verify_records)
    command = records.add_parser("rehash-authored")
    command.add_argument("record_id")
    command.set_defaults(handler=rehash_authored_record)
    installments = commands.add_parser("installments").add_subparsers(dest="installment_command", required=True)
    for name, handler in (("extract", extract_installments), ("list", list_installments)):
        command = installments.add_parser(name)
        command.add_argument("--year", type=int, required=True)
        command.set_defaults(handler=handler)
    command = installments.add_parser("next")
    command.add_argument("--year", type=int, required=True)
    command.add_argument("--as-of")
    command.set_defaults(handler=next_installment)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.handler(args)
    except (SatError, OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result} if args.json else result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
