#!/bin/bash
# Packs every AutoSketch drawing (.skf, and the older .skd) under a folder into a .tar.gz,
# keeping the folder structure.
#
#   bash collect_autosketch.sh /path/to/drawings [/path/to/output]
#
# Uses tar/gzip rather than zip, which some NAS systems don't ship.
set -euo pipefail

source_dir=${1:?usage: collect_autosketch.sh SOURCE_FOLDER [OUTPUT_FOLDER]}
mkdir -p "${2:-$PWD}"
output_dir=$(cd "${2:-$PWD}" && pwd)
source_dir=$(cd "$source_dir" && pwd)
archive="$output_dir/autosketch-$(date +%Y%m%d-%H%M).tar.gz"
list=$(mktemp)
trap 'rm -f "$list"' EXIT

cd "$source_dir"
find . -type f \( -iname '*.skf' -o -iname '*.skd' \) -not -path '*/.Recycle.Bin/*' -print0 > "$list"
drawings=$(tr -cd '\0' < "$list" | wc -c | tr -d ' ')

if [ "$drawings" -eq 0 ]; then
  echo "No AutoSketch files found under $source_dir" >&2
  exit 1
fi

echo "Found $drawings AutoSketch drawings. Packing into $archive ..."
tar -czf "$archive" --null -T "$list"
echo "Done: $(du -h "$archive" | cut -f1) in $archive"
