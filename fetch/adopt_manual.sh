#!/bin/bash
# Adopt manually downloaded files (registration / browser-only datasets).
#
#   1. Put the files in $RIRDB_ROOT/raw/_inbox/<id>/
#   2. sbatch jobs/download.sh fetch/adopt_manual.sh <id>
#
# Each file is hashed (sha256, trust on first use) into registry/locks/<id>.lock.tsv
# with url "manual:", moved into raw/<id>/_archives (archives) or raw/<id>/files,
# marked verified, then extracted and inventoried like any fetched dataset.

source "$(dirname "${BASH_SOURCE[0]}")/lib_common.sh"
HERE="$(dirname "${BASH_SOURCE[0]}")"

id=${1:?usage: adopt_manual.sh <dataset_id>}
load_row "$id"
inbox="$RIRDB_ROOT/raw/_inbox/$id"
[ -d "$inbox" ] && [ -n "$(ls -A "$inbox")" ] || die "$id: inbox $inbox is empty"
raw=$(raw_dir "$id"); okdir="$raw/.ok"
mkdir -p "$raw/_archives" "$raw/files" "$okdir" "$LOCKS_DIR"
lock="$LOCKS_DIR/$id.lock.tsv"
[ -f "$lock" ] || echo "$LOCK_HEADER" >"$lock"
now=$(date -u +%FT%TZ)
while IFS= read -r -d '' f; do
    rel=${f#"$inbox/"}
    if head -c 512 "$f" | tr 'A-Z' 'a-z' | grep -qE '^[[:space:]]*<(!doctype|html|head|body)'; then
        die "$rel is an HTML page, not data (download error?)"
    fi
    sum=$(sha256sum "$f" | cut -d' ' -f1)
    size=$(stat -c %s "$f")
    if is_archive "$rel"; then dest="$raw/_archives/$rel"; else dest="$raw/files/$rel"; fi
    mkdir -p "$(dirname "$dest")" "$(dirname "$okdir/$rel")"
    touch "$f"                          # fresh mtime (scratch purge is mtime based)
    mv -f "$f" "$dest"
    awk -F'\t' -v r="$rel" '$1 != r' "$lock" >"$lock.tmp" && mv "$lock.tmp" "$lock"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$rel" "manual:" "$size" "sha256" "$sum" "manual" "$now" >>"$lock"
    printf 'sha256\t%s\t%s\n' "$sum" "$now" >"$okdir/$rel.ok"
    log "adopted $rel ($(numfmt --to=iec "$size"))"
done < <(find "$inbox" -type f -print0 | sort -z)
state_set "$id" fetched_at "$(now_json)"
bash "$HERE/extract.sh" "$id"
bash "$HERE/inventory.sh" "$id"
log "adopt $id: done (commit registry/locks/$id.lock.tsv and registry/manifests/$id.files.tsv.gz)"
