#!/usr/bin/env bash
# Fetch ITU's reference code (CrashingGuru/ITUAIReadiness, MIT licence) into vendor/
# at the exact commit LinkDown was built and tested against.
# It is not committed to our repository (176 MB, includes third-party PDFs).
set -euo pipefail

REPO="https://github.com/CrashingGuru/ITUAIReadiness.git"
COMMIT="84010da9e9c443afcceeccb86d1700a662223395"
DEST="$(cd "$(dirname "$0")/.." && pwd)/vendor/ITUAIReadiness"

if [ -f "$DEST/simulation/server/knowledge/ingest.py" ]; then
  echo "already present: $DEST"
  exit 0
fi

mkdir -p "$(dirname "$DEST")"
git clone --filter=blob:none --no-checkout "$REPO" "$DEST"
git -C "$DEST" checkout --quiet "$COMMIT"
echo "ITU reference code at $COMMIT -> $DEST"
