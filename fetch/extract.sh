#!/bin/bash
# Extract fetched archives of a dataset into raw/<id>/files/.
#
#   fetch/extract.sh --wave 0
#   fetch/extract.sh tau_srir
#
# unzip -DD / tar --touch give extracted files fresh mtimes (scratch purges by
# mtime). Split zips (x.z01, x.z02, ..., x.zip) are joined first. Archives are
# deleted after a successful extraction when keep_archive is 0, or when "auto"
# and the dataset's archives exceed 5 GB (the lock is enough to re-fetch).

source "$(dirname "${BASH_SOURCE[0]}")/lib_common.sh"

AUTO_KEEP_MAX_BYTES=$((5 * 1024 * 1024 * 1024))

extract_archive() { # archive files_dir
    local a=$1 files=$2 base
    case "$a" in
        *.z[0-9][0-9]) return 0 ;;  # parts of a split zip; handled with the .zip
        *.zip)
            base=${a%.zip}
            if compgen -G "$base.z[0-9][0-9]" >/dev/null; then
                log "  joining split zip $(basename "$a")"
                local joined; joined=$(mktemp -d "$(dirname "$a")/join.XXXX")
                zip -q -s 0 "$a" --out "$joined/joined.zip"
                unzip -DD -q -o "$joined/joined.zip" -d "$files"
                rm -rf "$joined"
            else
                unzip -DD -q -o "$a" -d "$files"
            fi ;;
        *.tar|*.tar.gz|*.tgz|*.tbz2|*.tar.bz2|*.tar.xz)
            tar --touch --no-same-owner -xf "$a" -C "$files" ;;
        *) die "don't know how to extract $a" ;;
    esac
}

archive_stem() {
    local b; b=$(basename "$1")
    for ext in .tar.gz .tar.bz2 .tar.xz .tgz .tbz2 .tar .zip; do
        case "$b" in *"$ext") echo "${b%"$ext"}"; return ;; esac
    done
    echo "$b"
}

extract_one() {
    load_row "$1"
    local raw files okdir arch total keep n_arch
    raw=$(raw_dir "$D_ID"); files="$raw/files"; okdir="$raw/.ok"
    mkdir -p "$files"
    arch="$raw/_archives"
    # Several archives of one dataset may contain identical paths (e.g. C4DM's
    # three Omni.zip files all hold Omni/00x00y.wav): give each its own subfolder.
    # Decided from the lock, so a re-fetch lays files out identically.
    n_arch=$(tail -n +2 "$LOCKS_DIR/$D_ID.lock.tsv" | cut -f1 | grep -E '\.(zip|tar|tar\.gz|tgz|tbz2|tar\.bz2|tar\.xz)$' | wc -l)
    if [ ! -d "$arch" ] || [ -z "$(ls -A "$arch" 2>/dev/null)" ]; then
        log "extract $D_ID: nothing to extract"
        state_set "$D_ID" extracted_at "$(now_json)"
        return 0
    fi
    total=$(du -sb "$arch" | cut -f1)
    case "$D_KEEP" in
        1) keep=1 ;;
        0) keep=0 ;;
        *) keep=$([ "$total" -lt "$AUTO_KEEP_MAX_BYTES" ] && echo 1 || echo 0) ;;
    esac
    log "extract $D_ID ($(numfmt --to=iec "$total") of archives; keep=$keep)"
    local a rel
    while IFS= read -r a; do
        rel=${a#"$arch/"}
        [ -f "$okdir/$rel.ok" ] || { log "  skip unverified $rel"; continue; }
        [ -f "$okdir/$rel.extracted" ] && continue
        log "  $rel"
        if [ "$n_arch" -gt 1 ]; then
            mkdir -p "$files/$(archive_stem "$rel")"
            extract_archive "$a" "$files/$(archive_stem "$rel")"
        else
            extract_archive "$a" "$files"
        fi
        date -u +%FT%TZ >"$okdir/$rel.extracted"
    done < <(find "$arch" -type f ! -name '*.part' | sort)
    if [ "$keep" -eq 0 ]; then
        find "$arch" -type f ! -name '*.part' -print0 | while IFS= read -r -d '' a; do
            rel=${a#"$arch/"}
            case "$rel" in *.z[0-9][0-9]) rel="${rel%.z[0-9][0-9]}.zip" ;; esac
            [ -f "$okdir/$rel.extracted" ] && rm -f "$a"
        done
    fi
    state_set "$D_ID" extracted_at "$(now_json)"
    log "extract $D_ID: ok"
}

main() {
    local ids; ids=$(ids_from_args "$@")
    [ -n "$ids" ] || die "no datasets selected"
    local id
    for id in $ids; do extract_one "$id"; done
}

main "$@"
