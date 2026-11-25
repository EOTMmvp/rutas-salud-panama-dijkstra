"""Pruebas externas de humo: ejercitan el programa real sin utilizar Internet."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "rutas_salud_panama_floyd.py"


def run_app(*args):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(APP), *map(str, args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


class HospitalRoutingCLI(unittest.TestCase):
    def test_help_lists_entry_points(self):
        result = run_app("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--autotest", result.stdout)
        self.assertIn("--consulta", result.stdout)
        self.assertIn("--sin-osrm", result.stdout)

    def test_internal_self_tests(self):
        result = run_app("--autotest")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("40/40 pruebas correctas", result.stdout)

    def test_dataset_validation(self):
        result = run_app("--validar")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("93 instalaciones", result.stdout)
        self.assertIn("0 errores", result.stdout)

    def test_dataset_export_json(self):
        with tempfile.TemporaryDirectory(prefix="rutas_hospitalarias_tests_") as tmp:
            export = Path(tmp) / "dataset.json"
            result = run_app("--exportar-dataset", export)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(export.exists())
            data = json.loads(export.read_text(encoding="utf-8"))
            self.assertEqual(len(data), 93)

    def test_offline_consult(self):
        result = run_app("--sin-osrm", "--consulta", "8.98,-79.52", "--top", "3")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Origen (8.98000, -79.52000)", result.stdout)
        self.assertIn("POR CALLES (modelo)", result.stdout)


if __name__ == "__main__":
    unittest.main()
