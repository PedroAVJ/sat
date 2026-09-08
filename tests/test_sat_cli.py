from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sat_cli.py"
SPEC = importlib.util.spec_from_file_location("sat_cli", MODULE_PATH)
assert SPEC and SPEC.loader
sat_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sat_cli
SPEC.loader.exec_module(sat_cli)


class SatCliTests(unittest.TestCase):
    def test_import_is_private_idempotent_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "store"
            source = Path(temporary) / "record.md"
            source.write_text("private fixture\n")
            args = Namespace(source=str(source), record_id="fixture-record", kind="working-notes",
                             role="authored", destination=None, source_repository="private/example",
                             source_revision="abc123", source_path="old/record.md", git_blob="blob123")
            with patch.dict(os.environ, {"SAT_STORE_ROOT": str(root)}):
                first = sat_cli.import_record(args)
                second = sat_cli.import_record(args)
                verified = sat_cli.verify_records(Namespace())
                read = sat_cli.read_record(Namespace(record_id="fixture-record"))
            self.assertEqual(first["status"], "imported")
            self.assertEqual(second["status"], "unchanged")
            self.assertTrue(verified["valid"])
            self.assertEqual(read["content"], "private fixture\n")
            self.assertEqual((root / "index.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(Path(read["path"]).stat().st_mode & 0o777, 0o600)

            Path(read["path"]).write_text("deliberate authored revision\n")
            with patch.dict(os.environ, {"SAT_STORE_ROOT": str(root)}):
                revised = sat_cli.rehash_authored_record(Namespace(record_id="fixture-record"))
                verified_after_revision = sat_cli.verify_records(Namespace())
            self.assertEqual(revised["status"], "updated")
            self.assertEqual(len(revised["record"]["revision_history"]), 1)
            self.assertTrue(verified_after_revision["valid"])

    def test_parse_later_installment(self) -> None:
        text = """RFC: TEST010101AAA
NOMBRE: PERSONA DE PRUEBA
Documento: 123456 Parcialidad: 2/6 $13,855 $2,771
Número de Documento: 654321
Vigente hasta: 01/06/2026
Línea de Importe total 0000 TEST 1111 $2,771
"""
        row = sat_cli.parse_installment_text(text, source_record_id="installment-2",
            source_file="parcialidad-2.pdf", installment_number=2,
            total_installments=6, declaration_year=2025)
        self.assertEqual(row.amount_due_mxn, 2771.0)
        self.assertEqual(row.balance_after_payment_mxn, 11084.0)
        self.assertEqual(row.valid_until, "2026-06-01")

    def test_next_installment_never_claims_payment_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            derived = root / "derived/installments"
            derived.mkdir(parents=True)
            (derived / "2025.json").write_text(json.dumps([
                {"installment_number": 1, "valid_until": "2026-04-30"},
                {"installment_number": 2, "valid_until": "2026-06-01"}]))
            with patch.dict(os.environ, {"SAT_STORE_ROOT": str(root)}):
                result = sat_cli.next_installment(Namespace(year=2025, as_of="2026-05-01"))
            self.assertEqual(result["scheduled_installment"]["installment_number"], 2)
            self.assertEqual(result["payment_status"], "not tracked")


if __name__ == "__main__":
    unittest.main()
