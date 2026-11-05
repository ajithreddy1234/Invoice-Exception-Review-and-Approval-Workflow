#!/usr/bin/env python3
"""Local OCR memory baseline; rerun inside the deployment image for cloud evidence.

Each input runs in a fresh Python worker. Standard-library resource captures the
worker/child high-water RSS; ps samples combined worker + descendant RSS. No API,
credentials or invoice text are emitted. macOS and Linux are supported.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time

APP_ROOT = Path(__file__).resolve().parents[1]


def maxrss_bytes(who: int) -> int:
    value = resource.getrusage(who).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def child(path: Path, mime: str) -> dict:
    sys.path.insert(0, str(APP_ROOT))
    from app.extraction import read_document

    started = time.perf_counter()
    document = read_document(path.read_bytes(), mime)
    return {
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "worker_peak_rss_bytes": maxrss_bytes(resource.RUSAGE_SELF),
        "ocr_child_peak_rss_bytes": maxrss_bytes(resource.RUSAGE_CHILDREN),
        "pages": [{"method": page.method, "text_characters": len(page.text),
                   "low_confidence_token_count": len(page.low_confidence_tokens)}
                  for page in document.pages],
    }


def tree_rss(root_pid: int) -> int:
    """ps reports resident KiB on both supported platforms; no commands are read."""
    processes = []
    if sys.platform == 'linux':
        # The slim deployment image intentionally has no procps package. Read
        # kernel counters instead of silently losing process-tree measurement.
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields = entry.joinpath('status').read_text().splitlines()
                ppid = next(int(line.split()[1]) for line in fields if line.startswith('PPid:'))
                rss = next((int(line.split()[1]) for line in fields if line.startswith('VmRSS:')), 0)
                processes.append((int(entry.name), ppid, rss))
            except (OSError, ValueError, StopIteration):
                continue  # Process exited during the snapshot.
    else:
        result = subprocess.run(["ps", "-eo", "pid=,ppid=,rss="], capture_output=True,
                                text=True, check=True, timeout=3)
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 3:
                processes.append(tuple(int(part) for part in parts))
    descendants = {root_pid}
    while True:
        discovered = {pid for pid, ppid, _ in processes if ppid in descendants}
        if discovered <= descendants:
            break
        descendants |= discovered
    return sum(rss * 1024 for pid, _, rss in processes if pid in descendants)


def benchmark(path: Path, mime: str, interval: float) -> dict:
    command = [sys.executable, str(Path(__file__).resolve()), "--_child", str(path), "--mime", mime]
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True,
                               env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    peak = 0
    samples = 0
    sampling_error = None
    try:
        while process.poll() is None:
            if time.perf_counter() - started > 90:
                os.killpg(process.pid, signal.SIGKILL)
                raise TimeoutError(f"OCR benchmark exceeded 90 seconds for {path.name}")
            try:
                peak = max(peak, tree_rss(process.pid))
                samples += 1
            except (OSError, ValueError, subprocess.SubprocessError):
                sampling_error = "PROCESS_TREE_SAMPLING_UNAVAILABLE"
            time.sleep(interval)
        stdout, _ = process.communicate(timeout=3)
        if process.returncode != 0:
            return {"file": path.name, "status": "failed", "exit_code": process.returncode,
                    "error": "EXTRACTION_WORKER_FAILED"}
        result = json.loads(stdout)
        result.update({"file": path.name, "status": "completed", "mime_type": mime,
                       "total_worker_wall_seconds": round(time.perf_counter() - started, 4),
                       "sampled_process_tree_peak_rss_bytes": peak if samples else None,
                       "process_tree_samples": samples})
        if sampling_error:
            result["sampling_warning"] = sampling_error
        return result
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path,
                        default=APP_ROOT / "tests/fixtures")
    parser.add_argument("--output", type=Path,
                        default=APP_ROOT / "data/OCR-BENCHMARK.json")
    parser.add_argument("--sample-interval", type=float, default=0.03)
    parser.add_argument("--_child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--mime", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._child:
        print(json.dumps(child(args._child, args.mime)))
        return 0
    if sys.platform not in {"linux", "darwin"}:
        parser.error("This benchmark supports Linux and macOS resource RSS accounting.")
    if not 0.01 <= args.sample_interval <= 1:
        parser.error("Sampling interval must be between 0.01 and 1 second.")
    inputs = [("pdfs/scan_clean.pdf", "application/pdf"),
              ("pdfs/scan_blurred_total.pdf", "application/pdf"),
              ("images/scan_clean.jpg", "image/jpeg"),
              ("images/clean_invoice.png", "image/png")]
    for name, _ in inputs:
        if not (args.fixtures / name).is_file():
            parser.error(f"Missing fixture: {args.fixtures / name}")
    results = [benchmark(args.fixtures / name, mime, args.sample_interval) for name, mime in inputs]
    report = {
        "measurement_scope": "LOCAL_BASELINE_NOT_RENDER",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "system": platform.system(), "machine": platform.machine(),
        "python_version": platform.python_version(),
        "sample_interval_seconds": args.sample_interval,
        "notes": [
            "Fresh Python worker per input; no Gemini request or network API is used.",
            "worker_peak_rss_bytes is OS process high-water RSS; ocr_child_peak_rss_bytes is the OCR subprocess high-water RSS.",
            "sampled_process_tree_peak_rss_bytes sums worker and live descendants; sampling can miss brief peaks.",
            "RSS includes shared pages per process, so summed RSS may overstate unique physical memory.",
            "This is a local baseline, not proof that Render Free fits. Rerun in the deployed Linux container and observe its memory metrics.",
            "Benchmark runs serially; production concurrency must be separately bounded and measured.",
        ],
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if all(item["status"] == "completed" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
