"""Serving boundaries and source integrity for the local research workbench."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image
from vessel_reconstruction.server import WorkbenchServer, _run_id


class WorkbenchBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.artifacts = self.base / "artifacts"
        self.run = self.artifacts / "published-run"
        self.run.mkdir(parents=True)
        (self.run / "result.json").write_text(json.dumps({"vessel_id": "test-hull", "status": "review_required", "sections": [], "exports": {}}))
        (self.run / "source.png").write_bytes(b"test-source-bytes")
        (self.base / "private.txt").write_text("private workspace content")
        web = Path(__file__).resolve().parents[1] / "web"
        self.server = WorkbenchServer(("127.0.0.1", 0), self.artifacts, web)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.id = _run_id("published-run")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, payload=None, origin=None):
        headers = {}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        if origin:
            headers["Origin"] = origin
        return urlopen(Request(self.url + path, data=data, headers=headers), timeout=5)

    def test_inventory_contains_real_run_and_original_bytes(self):
        with self.request("/api/runs") as response:
            body = json.load(response)
        self.assertEqual(body["runs"][0]["name"], "test-hull")
        with self.request(f"/api/run/{self.id}/source.png") as response:
            self.assertEqual(response.read(), b"test-source-bytes")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_paths_and_symlinks_cannot_escape_declared_run(self):
        (self.run / "outside.json").symlink_to(self.base / "private.txt")
        for path in [f"/api/run/{self.id}/../../private.txt", f"/api/run/{_run_id('../')}/private.txt", f"/api/run/{self.id}/outside.json"]:
            with self.assertRaises(HTTPError) as caught:
                self.request(path)
            self.assertIn(caught.exception.code, [400, 404])

    def test_cross_origin_upload_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/reconstruct", {"spec": {}, "image_base64": "AA=="}, origin="https://unrelated.example")
        self.assertEqual(caught.exception.code, 403)

    def test_supporting_reference_cannot_read_an_existing_local_path(self):
        image = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(image, format="PNG")
        payload = {
            "spec": {"vessel_id": "unuploaded-reference", "source": {}, "station_reference": {"file": str(self.base / "private.txt")}},
            "image_base64": base64.b64encode(image.getvalue()).decode(),
        }
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/reconstruct", payload)
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("uploaded station-reference", json.load(caught.exception)["error"])
        self.assertFalse((self.artifacts / "uploads").exists())

    def test_supporting_reference_uses_uploaded_bytes_and_confined_path(self):
        image = io.BytesIO()
        reference = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(image, format="PNG")
        Image.new("RGB", (24, 30), "gray").save(reference, format="PNG")
        reference_raw = reference.getvalue()
        digest = hashlib.sha256(reference_raw).hexdigest()
        seen = {}

        def reconstruct(spec_path, output_dir, *, export_cad):
            spec = json.loads(Path(spec_path).read_text())
            ref = Path(spec_path).parent / spec["station_reference"]["file"]
            seen.update(path=ref, raw=ref.read_bytes(), reference=spec["station_reference"])
            return {"vessel_id": "uploaded-reference", "status": "review_required"}

        payload = {
            "spec": {"vessel_id": "uploaded-reference", "source": {}, "station_reference": {"file": str(self.base / "private.txt"), "sha256": digest}},
            "image_base64": base64.b64encode(image.getvalue()).decode(),
            "station_reference_base64": base64.b64encode(reference_raw).decode(),
        }
        with patch("vessel_reconstruction.pipeline.reconstruct", reconstruct):
            with self.request("/api/reconstruct", payload) as response:
                self.assertEqual(response.status, 202)
                job = json.load(response)
            for _ in range(30):
                with self.request(f"/api/jobs/{job['id']}") as response:
                    state = json.load(response)
                if state["state"] in {"complete", "failed"}:
                    break
                time.sleep(0.02)
            self.assertEqual(state["state"], "complete")
        self.assertEqual(seen["raw"], reference_raw)
        self.assertEqual(seen["reference"]["file"], "station_reference.png")
        self.assertEqual(seen["reference"]["sha256"], digest)
        self.assertIn(self.artifacts, seen["path"].parents)
        self.assertEqual((self.base / "private.txt").read_text(), "private workspace content")

    def test_upload_preserves_source_bytes_and_never_auto_approves(self):
        image = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(image, format="PNG")
        raw = image.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        seen = {}

        def reconstruct(spec_path, output_dir, *, export_cad):
            spec = json.loads(Path(spec_path).read_text())
            source = Path(spec_path).parent / spec["source"]["file"]
            seen.update(raw=source.read_bytes(), spec=spec)
            result = {"vessel_id": "upload", "status": "review_required", "review": {"engineering_approved": False}}
            (Path(output_dir) / "result.json").write_text(json.dumps(result))
            return result

        with patch("vessel_reconstruction.pipeline.reconstruct", reconstruct):
            with self.request("/api/reconstruct", {"spec": {"vessel_id": "upload", "source": {"file": "../../private.txt", "sha256": digest}, "sections": []}, "image_base64": base64.b64encode(raw).decode()}) as response:
                self.assertEqual(response.status, 202)
                job = json.load(response)
            for _ in range(30):
                with self.request(f"/api/jobs/{job['id']}") as response:
                    state = json.load(response)
                if state["state"] == "complete":
                    break
                time.sleep(0.02)
            self.assertEqual(state["state"], "complete")
            self.assertEqual(seen["raw"], raw)
            self.assertEqual(seen["spec"]["source"]["sha256"], digest)
            self.assertEqual(seen["spec"]["source"]["file"], "drawing.png")
            with self.request(f"/api/run/{state['run_id']}/result.json") as response:
                result = json.load(response)
            self.assertFalse(result["review"]["engineering_approved"])


if __name__ == "__main__":
    unittest.main()
