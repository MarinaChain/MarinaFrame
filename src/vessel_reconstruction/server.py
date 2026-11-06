"""Local, dependency-free inspection workbench.

The server binds to loopback by default. It serves only declared artifact roots,
never approves engineering output, and runs reconstruction jobs serially.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import mimetypes
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

MAX_REQUEST_BYTES = 48 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_REFERENCE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 80_000_000


def _run_id(relative: str) -> str:
    return base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,1200}", value):
        raise ValueError("Invalid run identifier")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")


def _contained(root: Path, target: Path) -> Path:
    root = root.resolve()
    target = target.resolve()
    if target != root and root not in target.parents:
        raise ValueError("Requested path is outside the artifact root")
    return target


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def find_runs(artifacts: Path) -> list[dict[str, Any]]:
    """Discover real pipeline results; benchmark ground truth is never a run."""
    artifacts = artifacts.resolve()
    found: list[dict[str, Any]] = []
    for file in artifacts.rglob("result.json"):
        try:
            _contained(artifacts, file)
            result = _load_json(file)
            if "status" not in result or "vessel_id" not in result:
                continue
            relative = file.parent.relative_to(artifacts).as_posix()
            metrics = result.get("metrics") or {}
            found.append({
                "id": _run_id(relative),
                "name": result.get("vessel_id", file.parent.name),
                "run_id": result.get("run_id"),
                "status": result.get("status", "unknown"),
                "path": relative,
                "modified": file.stat().st_mtime,
                "sections": len(result.get("sections") or []),
                "volume_m3": metrics.get("volume_m3"),
                "has_mesh": bool((result.get("exports") or {}).get("mesh")),
            })
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(found, key=lambda value: value["modified"], reverse=True)


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], artifacts: Path, web_root: Path):
        self.artifacts = artifacts.resolve()
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.web_root = web_root.resolve()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.jobs_lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reconstruction")
        super().__init__(address, WorkbenchHandler)

    def server_close(self) -> None:
        super().server_close()
        self.executor.shutdown(wait=False, cancel_futures=True)


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer
    server_version = "VesselWorkbench/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Avoid logging uploaded content or request headers.
        print(f"[workbench] {self.address_string()} {fmt % args}", flush=True)

    def _headers(self, status: int, length: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _json(self, value: Any, status: int = 200) -> None:
        raw = json.dumps(value, allow_nan=False, default=str).encode("utf-8")
        self._headers(status, len(raw), "application/json; charset=utf-8")
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._json({"error": "File not found"}, 404)
            return
        raw = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        if path.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        self._headers(200, len(raw), content_type)
        if self.command != "HEAD":
            self.wfile.write(raw)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/runs":
                self._json({"runs": find_runs(self.server.artifacts)})
                return
            if path == "/api/health":
                self._json({"status": "ok", "service": "vessel-reconstruction-workbench", "engineering_approval": False})
                return
            if path.startswith("/api/jobs/"):
                job_id = path.removeprefix("/api/jobs/")
                with self.server.jobs_lock:
                    job = dict(self.server.jobs.get(job_id) or {})
                self._json(job or {"error": "Job not found"}, 200 if job else 404)
                return
            if path.startswith("/api/run/"):
                pieces = path.removeprefix("/api/run/").split("/", 1)
                if len(pieces) != 2:
                    raise ValueError("Missing artifact filename")
                relative = _decode_run_id(pieces[0])
                run_root = _contained(self.server.artifacts, self.server.artifacts / relative)
                if not (run_root / "result.json").is_file():
                    self._json({"error": "Run not found"}, 404)
                    return
                asset = _contained(run_root, run_root / pieces[1])
                # Do not expose hidden files or executable source through artifact URLs.
                if any(part.startswith(".") for part in Path(pieces[1]).parts):
                    raise ValueError("Hidden files are not served")
                if asset.suffix.lower() not in {".json", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".step", ".stp", ".stl", ".glb", ".gltf", ".pdf"}:
                    raise ValueError("Unsupported artifact type")
                self._file(asset)
                return
            if path in {"/", "/index.html"}:
                self._file(self.server.web_root / "index.html")
                return
            if path in {"/app.js", "/style.css"}:
                self._file(self.server.web_root / path.lstrip("/"))
                return
            self._json({"error": "Not found"}, 404)
        except (ValueError, binascii.Error, UnicodeError):
            self._json({"error": "Invalid artifact path"}, 400)
        except OSError:
            self._json({"error": "The requested artifact could not be read"}, 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/reconstruct":
            self._json({"error": "Not found"}, 404)
            return
        # Reject cross-origin browser uploads to a user's local service.
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self._json({"error": "Cross-origin uploads are not allowed"}, 403)
            return
        if self.headers.get_content_type() != "application/json":
            self._json({"error": "Send application/json"}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._json({"error": "Request must be between 1 byte and 48 MiB"}, 413)
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or not isinstance(payload.get("spec"), dict):
                raise ValueError("A drawing specification object is required")
            encoded = payload.get("image_base64")
            if not isinstance(encoded, str):
                raise ValueError("A drawing image is required")
            if "," in encoded and encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[1]
            raw = base64.b64decode(encoded, validate=True)
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("Drawing must be no larger than 20 MiB")
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Drawing exceeds 80 million pixels")
                if image.format not in {"PNG", "JPEG", "TIFF", "BMP", "WEBP"}:
                    raise ValueError("Use a PNG, JPEG, TIFF, BMP or WebP drawing")
                extension = {"PNG": ".png", "JPEG": ".jpg", "TIFF": ".tiff", "BMP": ".bmp", "WEBP": ".webp"}[image.format]
                image.verify()
            # Preserve original bytes so uploaded source hashes remain verifiable.
            image_name = "drawing" + extension
            spec = json.loads(json.dumps(payload["spec"]))
            reference_raw = None
            reference_name = None
            if spec.get("station_reference") is not None:
                if not isinstance(spec["station_reference"], dict):
                    raise ValueError("station_reference must be an object")
                reference_encoded = payload.get("station_reference_base64")
                if not isinstance(reference_encoded, str):
                    raise ValueError("This specification requires an uploaded station-reference document; local file paths are not accepted by the browser API")
                if reference_encoded.startswith("data:") and "," in reference_encoded:
                    reference_encoded = reference_encoded.split(",", 1)[1]
                reference_raw = base64.b64decode(reference_encoded, validate=True)
                if not reference_raw or len(reference_raw) > MAX_REFERENCE_BYTES:
                    raise ValueError("Station reference must be no larger than 12 MiB")
                if reference_raw.startswith(b"%PDF-"):
                    try:
                        import fitz
                    except ImportError as exc:
                        raise ValueError("PDF references need the optional documents dependencies") from exc
                    with fitz.open(stream=reference_raw, filetype="pdf") as document:
                        if document.page_count < 1:
                            raise ValueError("Station reference PDF has no pages")
                    reference_name = "station_reference.pdf"
                else:
                    with Image.open(io.BytesIO(reference_raw)) as reference_image:
                        if reference_image.width * reference_image.height > MAX_IMAGE_PIXELS:
                            raise ValueError("Station reference exceeds 80 million pixels")
                        extensions = {"PNG": ".png", "JPEG": ".jpg", "TIFF": ".tiff", "BMP": ".bmp", "WEBP": ".webp"}
                        if reference_image.format not in extensions:
                            raise ValueError("Station reference must be a supported image or PDF")
                        reference_name = "station_reference" + extensions[reference_image.format]
                        reference_image.verify()
            job_id = uuid4().hex[:16]
            vessel = re.sub(r"[^A-Za-z0-9_-]", "-", str(spec.get("vessel_id", "uploaded-drawing")))[:70].strip("-") or "uploaded-drawing"
            relative = f"uploads/{time.strftime('%Y%m%d-%H%M%S')}-{vessel}-{job_id[:6]}"
            output = self.server.artifacts / relative
            input_dir = output / "input"
            input_dir.mkdir(parents=True, exist_ok=False)
            (input_dir / image_name).write_bytes(raw)
            if reference_raw is not None and reference_name:
                (input_dir / reference_name).write_bytes(reference_raw)
                spec["station_reference"]["file"] = reference_name
            if not isinstance(spec.get("source"), dict):
                spec["source"] = {}
            spec["source"]["file"] = image_name
            spec["source"]["upload_original_sha256"] = hashlib.sha256(raw).hexdigest()
            spec_file = input_dir / "spec.json"
            spec_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
            job = {"id": job_id, "state": "queued", "vessel_id": spec.get("vessel_id", vessel), "created": time.time()}
            with self.server.jobs_lock:
                self.server.jobs[job_id] = job
            self.server.executor.submit(self._reconstruct_job, self.server, job_id, spec_file, output, relative)
            self._json(job, 202)
        except (ValueError, binascii.Error, OSError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": f"Drawing could not be read: {type(exc).__name__}"}, 400)

    @staticmethod
    def _reconstruct_job(server: WorkbenchServer, job_id: str, spec_file: Path, output: Path, relative: str) -> None:
        started = time.monotonic()
        with server.jobs_lock:
            server.jobs[job_id].update(state="running")
        try:
            from vessel_reconstruction.pipeline import reconstruct
            result = reconstruct(spec_file, output, export_cad=True)
            with server.jobs_lock:
                server.jobs[job_id].update(state="complete", result_status=result.get("status"), run_id=_run_id(relative), elapsed_seconds=round(time.monotonic() - started, 3))
        except Exception as exc:
            traceback.print_exc()
            with server.jobs_lock:
                server.jobs[job_id].update(state="failed", error=f"{type(exc).__name__}: {str(exc)[:500]}", elapsed_seconds=round(time.monotonic() - started, 3))


def serve(artifacts_dir: str | Path = "artifacts", host: str = "127.0.0.1", port: int = 8765) -> None:
    project_root = Path(__file__).resolve().parents[2]
    candidates = [Path(__file__).resolve().parent / "web", project_root / "web"]
    web_root = next((path for path in candidates if (path / "index.html").is_file()), None)
    if web_root is None:
        raise FileNotFoundError("Workbench web assets were not found. Run from the source bundle or install package data.")
    server = WorkbenchServer((host, port), Path(artifacts_dir), web_root)
    print(f"Vessel Workbench: http://{host}:{server.server_address[1]}", flush=True)
    print("Research reconstruction only. Engineer review is required.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect vessel reconstruction artifacts locally")
    parser.add_argument("--artifacts", default="artifacts")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.artifacts, args.host, args.port)


if __name__ == "__main__":
    main()


def write_snapshot(run_dir: str | Path, output_file: str | Path) -> Path:
    """Create a self-contained, offline evidence viewer for one real result.

    It embeds the recorded result, mesh and source images. Available CAD exports
    are included up to a generous size limit; omitted downloads are hidden. The
    snapshot never adds geometry, alters metrics or enables engineering approval.
    """
    run_dir = Path(run_dir).resolve()
    result_path = _contained(run_dir, run_dir / "result.json")
    result = _load_json(result_path)
    package_root = Path(__file__).resolve().parent
    web_root = package_root / "web"
    if not web_root.is_dir():
        web_root = package_root.parents[1] / "web"
    files = {"result.json"}
    exports = result.get("exports") or {}
    for key in ("mesh", "step", "stl"):
        if isinstance(exports.get(key), str):
            files.add(exports[key])
    for source in result.get("sources") or []:
        for key in ("file", "preview_file"):
            if isinstance(source.get(key), str):
                files.add(source[key])
    assets = {}
    omitted = []
    for name in sorted(files):
        try:
            path = _contained(run_dir, run_dir / name)
            if not path.is_file():
                omitted.append(name)
                continue
            if path.stat().st_size > 20 * 1024 * 1024:
                omitted.append(name)
                continue
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            assets[name] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        except (OSError, ValueError):
            omitted.append(name)
    payload = {
        "vessel_id": result.get("vessel_id", "Reconstruction"),
        "status": result.get("status", "unknown"),
        "assets": assets,
        "omitted_oversize_artifacts": omitted,
    }
    bootstrap = "window.__VESSEL_SNAPSHOT__=" + json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c") + ";"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    css = (web_root / "style.css").read_text(encoding="utf-8")
    js = (web_root / "app.js").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/style.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="/app.js" defer></script>', "")
    html = html.replace('</body>', f"<script>{bootstrap}</script>\n<script>\n{js}\n</script>\n</body>")
    output_file = Path(output_file).resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")
    return output_file
