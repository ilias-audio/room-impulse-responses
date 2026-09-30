#!/bin/bash
# resolve -> fetch -> extract -> inventory for the selected datasets, one
# dataset at a time (so a failure in one does not block the others).
#
#   sbatch jobs/download.sh fetch/run.sh --wave 0
#   sbatch jobs/download.sh fetch/run.sh ace rochester
#
# Set SKIP_RESOLVE=1 to reuse the committed lock files as they are.

source "$(dirname "${BASH_SOURCE[0]}")/lib_common.sh"
HERE="$(dirname "${BASH_SOURCE[0]}")"

ids=$(ids_from_args "$@")
[ -n "$ids" ] || die "no datasets selected"
failed=()
for id in $ids; do
    log "===== $id ====="
    if { [ "${SKIP_RESOLVE:-0}" = 1 ] || bash "$HERE/resolve.sh" "$id"; } \
        && bash "$HERE/fetch.sh" "$id" \
        && bash "$HERE/extract.sh" "$id" \
        && bash "$HERE/inventory.sh" "$id"; then
        log "===== $id: done ====="
    else
        log "===== $id: FAILED ====="
        failed+=("$id")
    fi
done
if [ ${#failed[@]} -gt 0 ]; then
    log "failed: ${failed[*]}"
    exit 1
fi
log "all done: $(echo $ids | wc -w) dataset(s)"
