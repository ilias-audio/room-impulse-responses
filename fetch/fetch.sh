#!/bin/bash
# Download the files listed in registry/locks/<id>.lock.tsv, resumably, and
# verify each against its lock checksum. Idempotent: verified files carry a
# marker in raw/<id>/.ok/ and are skipped on re-runs.
#
#   fetch/fetch.sh --wave 0
#   fetch/fetch.sh ace rochester
#
# Archives go to raw/<id>/_archives/ (then fetch/extract.sh), everything else
# straight to raw/<id>/files/. curl never restores server mtimes (no -R), so
# new files are not purge-eligible on arrival.

source "$(dirname "${BASH_SOURCE[0]}")/lib_common.sh"

MAX_ATTEMPTS=${MAX_ATTEMPTS:-3}

hash_file() { # algo file
    case "$1" in
        md5) md5sum "$2" | cut -d' ' -f1 ;;
        sha256) sha256sum "$2" | cut -d' ' -f1 ;;
        *) die "unsupported checksum algorithm $1" ;;
    esac
}

# Record a trust-on-first-use sha256 into the lock file.
record_tofu() { # lockfile relpath sha256
    local tmp; tmp=$(mktemp "$1.XXXX")
    awk -F'\t' -v OFS='\t' -v r="$2" -v s="$3" 'NR>1 && $1==r && $5=="-" {$4="sha256"; $5=s} {print}' "$1" >"$tmp" && mv "$tmp" "$1"
}

download() { # url dest  (resumable; falls back to a fresh download if ranges unsupported)
    local url=$1 dest=$2 attempt rc
    for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
        rc=0
        curl -fL -C - --retry 8 --retry-all-errors --retry-delay 15 --connect-timeout 60 \
             -sS -A "$UA" -o "$dest" "$url" || rc=$?
        [ $rc -eq 0 ] && return 0
        if [ $rc -eq 33 ] || [ $rc -eq 36 ]; then   # range not supported / bad resume
            log "  server refused resume (curl $rc); restarting from zero"
            rm -f "$dest"
        fi
        log "  curl exit $rc (attempt $attempt/$MAX_ATTEMPTS)"
        sleep $((attempt * 30))
    done
    return 1
}

fetch_mirror() { # url
    local url=$1 files cut
    files="$(raw_dir "$D_ID")/files"
    mkdir -p "$files"
    # number of path components to cut so files land directly under files/
    cut=$(awk -F/ '{n=0; for (i=4;i<=NF;i++) if ($i!="") n++; print n}' <<<"$url")
    local accept; accept=$(split_list "$D_ACCEPT" | paste -sd, -)
    log "  mirroring $url (accept: ${accept:-all})"
    # -nc (no-clobber) instead of -m/-N: keeps it idempotent without restoring
    # server timestamps (which would make files purge-eligible on arrival).
    wget -r -np -nH --cut-dirs="$cut" -nc -e robots=off --no-verbose \
         --no-use-server-timestamps --tries=10 --waitretry=10 \
         --reject-regex '/(examples|images)/|\?C=' \
         ${accept:+-A "$accept"} -P "$files" "$url" 2>&1 | tail -n 3 >&2 || true
    find "$files" -name 'index.html*' -delete
}

fetch_one() {
    load_row "$1"
    local lock="$LOCKS_DIR/$D_ID.lock.tsv" raw okdir failures=0
    [ -f "$lock" ] || die "$D_ID: no lock file; run fetch/resolve.sh $D_ID first"
    raw=$(raw_dir "$D_ID"); okdir="$raw/.ok"
    mkdir -p "$raw/_archives" "$raw/files" "$okdir"
    log "fetch $D_ID"
    local relpath url size algo checksum version resolved dest marker got
    while IFS=$'\t' read -r relpath url size algo checksum version resolved; do
        if [ "$relpath" = "@mirror" ]; then fetch_mirror "$url"; continue; fi
        if is_archive "$relpath"; then dest="$raw/_archives/$relpath"; else dest="$raw/files/$relpath"; fi
        marker="$okdir/$relpath.ok"
        if [ -f "$marker" ] && { [ -f "$dest" ] || [ -f "$okdir/$relpath.extracted" ]; }; then
            if [ "$checksum" = "-" ] || grep -q "$checksum" "$marker"; then continue; fi
        fi
        mkdir -p "$(dirname "$dest")" "$(dirname "$marker")"
        # Already on disk without a marker (e.g. after `rirdb verify --repair`): adopt if it verifies.
        if [ -f "$dest" ] && [ "$checksum" != "-" ] && [ "$(hash_file "$algo" "$dest")" = "$checksum" ]; then
            printf '%s\t%s\t%s\n' "$algo" "$checksum" "$(date -u +%FT%TZ)" >"$marker"
            continue
        fi
        log "  $relpath ($( [ "$size" = "-" ] && echo "size ?" || numfmt --to=iec "$size"))"
        if ! download "$url" "$dest.part"; then
            log "  FAILED $relpath"; failures=$((failures + 1)); continue
        fi
        # Servers/firewalls sometimes answer 200 with an HTML error page: never
        # accept (or trust-on-first-use) HTML in place of a data file.
        case "$relpath" in
            *.html|*.htm|*.txt|*.md|*.csv|*.bib) ;;
            *) if head -c 512 "$dest.part" | tr 'A-Z' 'a-z' | grep -qE '^[[:space:]]*<(!doctype|html|head|body)'; then
                   log "  REJECTED $relpath: server returned an HTML page ($(head -c 120 "$dest.part" | tr -d '\n'))"
                   rm -f "$dest.part"; failures=$((failures + 1)); continue
               fi ;;
        esac
        if [ "$size" != "-" ] && [ "$(stat -c %s "$dest.part")" != "$size" ]; then
            log "  SIZE MISMATCH $relpath: got $(stat -c %s "$dest.part"), expected $size"
            rm -f "$dest.part"; failures=$((failures + 1)); continue
        fi
        if [ "$checksum" = "-" ]; then
            got=$(hash_file sha256 "$dest.part"); algo=sha256
            record_tofu "$lock" "$relpath" "$got"
            log "  recorded sha256 (trust on first use)"
        else
            got=$(hash_file "$algo" "$dest.part")
            if [ "$got" != "$checksum" ]; then
                log "  CHECKSUM MISMATCH $relpath: $algo $got != $checksum"
                rm -f "$dest.part"; failures=$((failures + 1)); continue
            fi
        fi
        mv -f "$dest.part" "$dest"
        printf '%s\t%s\t%s\n' "$algo" "$got" "$(date -u +%FT%TZ)" >"$marker"
    done < <(tail -n +2 "$lock")
    if [ $failures -gt 0 ]; then
        log "fetch $D_ID: $failures file(s) failed"
        return 1
    fi
    state_set "$D_ID" fetched_at "$(now_json)"
    log "fetch $D_ID: ok"
}

main() {
    local ids; ids=$(ids_from_args "$@")
    [ -n "$ids" ] || die "no datasets selected"
    local id rc=0
    for id in $ids; do fetch_one "$id" || rc=1; done
    return $rc
}

main "$@"
