"""Standalone debug script: exercises extract_text() directly on a file,
bypassing the browser and the HTTP layer entirely, to isolate whether an
upload failure is coming from extraction itself (OCR/PIL/pypdf crashing
or hanging) versus something in the network path (which is what a
browser-side "Failed to fetch" with no server-side error log usually
means -- the connection died before a response was ever sent).

Usage (from services/orchestrator, with the venv active):

    .venv\\Scripts\\python debug_upload.py "C:\\path\\to\\the\\file.png"

Delete this file once you're done with it -- it's a one-off diagnostic,
not part of the app.
"""

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, ".")


def main():
    if len(sys.argv) != 2:
        print("Usage: python debug_upload.py <path-to-file>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    raw_bytes = path.read_bytes()
    print(f"File: {path.name}")
    print(f"Size: {len(raw_bytes):,} bytes ({len(raw_bytes) / 1_000_000:.2f} MB)")

    from app.main import MAX_UPLOAD_BYTES

    print(f"Upload size limit: {MAX_UPLOAD_BYTES:,} bytes")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        print("*** THIS FILE EXCEEDS THE SIZE LIMIT -- that would be your problem. ***")
        print("(Though the server should reject it with a clean 400, not a dead connection.)")

    from app.extract import UnsupportedFileType, extract_text

    print("\nRunning extract_text() -- the exact function /upload calls...")
    start = time.time()
    try:
        text = extract_text(path.name, raw_bytes)
    except UnsupportedFileType as exc:
        elapsed = time.time() - start
        print(f"\nUnsupportedFileType after {elapsed:.1f}s (a normal, handled error): {exc}")
        return
    except Exception:
        elapsed = time.time() - start
        print(f"\n*** UNEXPECTED EXCEPTION after {elapsed:.1f}s ***")
        print("This is very likely what's crashing the server connection and")
        print("showing up in the browser as \"Failed to fetch\". Full traceback:\n")
        traceback.print_exc()
        return

    elapsed = time.time() - start
    print(f"\nSucceeded in {elapsed:.1f}s")
    print(f"Extracted text length: {len(text)} characters")
    print(f"First 500 characters:\n{text[:500]!r}")


if __name__ == "__main__":
    main()
