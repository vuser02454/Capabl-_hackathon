"""Download TACO images at the 640px size, in parallel, resumably.

TACO's own `download.py` fetches `flickr_url` (full resolution): roughly 2.7 GB and ~40 minutes
for 1,500 images, serially. Detector training resizes to 640px anyway, and YOLO labels are
normalised against the dimensions recorded in the annotation file, so box coordinates are
resolution-independent — the smaller images carry exactly the same supervision for a tenth of the
bytes.

Already-present files are skipped, so this is safe to re-run after an interruption.

    python training/download_taco_images.py --taco TACO-master --workers 12
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


def fetch(image: dict, data_dir: Path, timeout: float) -> tuple:
    target = data_dir / image["file_name"]
    if target.is_file() and target.stat().st_size > 0:
        return ("skipped", image["file_name"], None)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Prefer the 640px render; fall back to the original only if it is absent.
    url = image.get("flickr_640_url") or image.get("flickr_url")
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        target.write_bytes(response.content)
        return ("downloaded", image["file_name"], len(response.content))
    except Exception as exc:  # noqa: BLE001 - one bad URL must not stop the set
        return ("failed", image["file_name"], f"{exc.__class__.__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taco", default="TACO-master")
    parser.add_argument("--annotations", default="data/annotations.json")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    root = Path(args.taco)
    data = json.loads((root / args.annotations).read_text())
    data_dir = root / "data"

    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    failures = []
    total_bytes = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch, image, data_dir, args.timeout) for image in data["images"]]
        for done, future in enumerate(as_completed(futures), start=1):
            status, name, extra = future.result()
            counts[status] += 1
            if status == "downloaded" and isinstance(extra, int):
                total_bytes += extra
            elif status == "failed":
                failures.append({"file": name, "error": extra})
            if done % 100 == 0 or done == len(futures):
                print(f"  {done}/{len(futures)}  {counts}", flush=True)

    print(f"\ndownloaded {counts['downloaded']}  skipped {counts['skipped']}  failed {counts['failed']}")
    print(f"total {total_bytes / 1_000_000:.0f} MB")
    if failures:
        # Listed, not hidden: a missing image becomes a missing training sample.
        print("failures (first 10):")
        for failure in failures[:10]:
            print(f"  {failure['file']}: {failure['error']}")


if __name__ == "__main__":
    main()
