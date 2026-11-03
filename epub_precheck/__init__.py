"""epub-precheck: validate EPUB 3 files before you upload them.

A local-first, stdlib-only pre-checker that catches the common
upload-stoppers (bad mimetype, broken spine, missing nav, dead image
references, missing cover, oversized files) and prints a friendly,
fix-by-fix report.

Copyright (c) 2026 Asdale Dynamics, LLC. MIT licensed.
"""

__version__ = "1.0.0"
