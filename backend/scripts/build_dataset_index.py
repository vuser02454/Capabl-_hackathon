"""Build the water reference-dataset index used by services/water_dataset_match_service.py.

    python scripts/build_dataset_index.py [--force]

The API builds this lazily in a background thread on first use too; running it ahead of time
means the first upload does not have to wait. Needs pillow + numpy.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.water_dataset_match_service import MatchUnavailable, get_dataset_matcher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild even if a cached index exists")
    args = parser.parse_args()

    matcher = get_dataset_matcher()
    if args.force and matcher.index_path.exists():
        matcher.index_path.unlink()

    print(f"Reference images : {matcher.images_path}")
    print(f"Index file       : {matcher.index_path}")
    started = time.time()
    try:
        matcher.build()
    except MatchUnavailable as exc:
        print(f"\nFailed: {exc.message}", file=sys.stderr)
        return 1

    info = matcher.describe()
    elapsed = time.time() - started
    print(f"\nIndexed {info['datasetSize']} images in {elapsed:.1f}s")
    for class_name, count in sorted(info["classes"].items()):
        print(f"  {class_name:<12} {count}")
    print(f"Size on disk     : {matcher.index_path.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
