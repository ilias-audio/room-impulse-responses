#!/bin/bash
# Write registry/manifests/<id>.files.tsv.gz: every file under raw/<id>/files
# with its size and sha256. Committed to git, so `rirdb verify` can detect
# missing (e.g. purged) or modified files later.
#
#   fetch/inventory.sh --wave 0
#   fetch/inventory.sh ace

source "$(dirname "${BASH_SOURCE[0]}")/lib_common.sh"

JOBS=${INVENTORY_JOBS:-${SLURM_CPUS_PER_TASK:-4}}

inventory_one() {
    load_row "$1"
    local files out n bytes digest
    files="$(raw_dir "$D_ID")/files"
    [ -d "$files" ] || die "$D_ID: $files does not exist"
    out="$MANIFESTS_DIR/$D_ID.files.tsv.gz"
    mkdir -p "$MANIFESTS_DIR"
    log "inventory $D_ID (hashing with $JOBS processes)"
    (
        cd "$files"
        printf 'relpath\tsize\tsha256\n'
        find . -type f ! -name '*.part' -printf '%P\0' | sort -z \
        | xargs -0 -r -n 64 -P "$JOBS" sh -c 'for f; do printf "%s\t%s\t%s\n" "$f" "$(stat -c %s "$f")" "$(sha256sum "$f" | cut -d" " -f1)"; done' _ \
        | LC_ALL=C sort -t$'\t' -k1,1
    ) | gzip -n >"$out.tmp" && mv "$out.tmp" "$out"
    n=$(($(zcat "$out" | wc -l) - 1))
    bytes=$(zcat "$out" | awk -F'\t' 'NR>1 {s+=$2} END{printf "%.0f", s}')
    digest=$(zcat "$out" | tail -n +2 | sha256sum | cut -d' ' -f1)
    state_set "$D_ID" inventory "$(jq -n --argjson n "$n" --argjson b "$bytes" --arg d "$digest" --arg t "$(date -u +%FT%TZ)" '{n_files:$n, bytes:$b, tree_sha256:$d, at:$t}')"
    log "inventory $D_ID: $n files, $(numfmt --to=iec "$bytes")"
}

main() {
    local ids; ids=$(ids_from_args "$@")
    [ -n "$ids" ] || die "no datasets selected"
    local id
    for id in $ids; do inventory_one "$id"; done
}

main "$@"
