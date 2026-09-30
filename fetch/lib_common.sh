#!/bin/bash
# Shared helpers for the network layer (bash + curl + jq; no Python).
# Sourced by fetch/*.sh. Reads registry/compiled/sources.tsv, which
# `rirdb registry compile` generates from registry/datasets.yaml.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$REPO_ROOT/.env" ]; then
    set -a; source "$REPO_ROOT/.env"; set +a
fi
RIRDB_ROOT="${RIRDB_ROOT:-/gpfs/scratch/eey119/rir-data}"
SOURCES_TSV="$REPO_ROOT/registry/compiled/sources.tsv"
LOCKS_DIR="$REPO_ROOT/registry/locks"
MANIFESTS_DIR="$REPO_ROOT/registry/manifests"
UA="rirdb/0.1 (+https://github.com/ilias-audio/room-impulse-responses)"
LOCK_HEADER=$'relpath\turl\tsize\talgo\tchecksum\tprovider_version\tresolved_at'

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

curl_json() {
    curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 -m 180 -A "$UA" "$1"
}

# Content-Length of the final response after redirects ("-" if unknown).
http_size() {
    local n
    n=$(curl -sIL -m 60 -A "$UA" "$1" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')
    echo "${n:--}"
}

# ETag / Last-Modified of the final response, as a provenance string.
http_version() {
    curl -sIL -m 60 -A "$UA" "$1" | tr -d '\r' \
        | awk 'tolower($1)=="etag:"{e=$2} tolower($1)=="last-modified:"{sub(/^[^:]*: /,""); m=$0} END{printf "etag=%s;last-modified=%s", e, m}' \
        | tr '\t' ' '
}

urldecode() { local s="${1//+/ }"; printf '%b' "${s//%/\\x}"; }

# load_row <id>: sets D_ID D_WAVE D_STATUS D_ACCESS D_KIND D_RECORDS D_URLS
#                D_INCLUDE D_EXCLUDE D_ACCEPT D_KEEP from sources.tsv
load_row() {
    local line
    [ -f "$SOURCES_TSV" ] || die "$SOURCES_TSV missing: run 'rirdb registry compile' (via sbatch) first"
    line=$(awk -F'\t' -v id="$1" 'NR>1 && $1==id' "$SOURCES_TSV")
    [ -n "$line" ] || die "unknown dataset id '$1'"
    IFS=$'\t' read -r D_ID D_WAVE D_STATUS D_ACCESS D_KIND D_RECORDS D_URLS \
        D_INCLUDE D_EXCLUDE D_ACCEPT D_KEEP <<<"$line"
}

# Print the '|'-joined list field one item per line ("-" = empty).
split_list() { [ "$1" = "-" ] || tr '|' '\n' <<<"$1"; }

# selected <file name>: true if it passes the dataset include/exclude globs.
selected() {
    local name=$1 g ok=1
    if [ "$D_INCLUDE" != "-" ]; then
        ok=0
        while IFS= read -r g; do
            # shellcheck disable=SC2053  # $g is a glob on purpose
            if [[ $name == $g ]]; then ok=1; break; fi
        done < <(split_list "$D_INCLUDE")
    fi
    [ $ok -eq 1 ] || return 1
    if [ "$D_EXCLUDE" != "-" ]; then
        while IFS= read -r g; do
            # shellcheck disable=SC2053
            if [[ $name == $g ]]; then return 1; fi
        done < <(split_list "$D_EXCLUDE")
    fi
    return 0
}

# ids_from_args [--wave N]... [--all] [id...]: dataset ids to process, one per
# line. Waves select datasets that are open and planned/active.
ids_from_args() {
    [ -f "$SOURCES_TSV" ] || die "$SOURCES_TSV missing: run 'rirdb registry compile' first"
    local waves=() ids=() all=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --wave) waves+=("$2"); shift 2 ;;
            --all) all=1; shift ;;
            -*) die "unknown option $1" ;;
            *) ids+=("$1"); shift ;;
        esac
    done
    for w in "${waves[@]+"${waves[@]}"}"; do
        awk -F'\t' -v w="$w" 'NR>1 && $2==w && $4=="open" && ($3=="planned" || $3=="active") {print $1}' "$SOURCES_TSV"
    done
    if [ $all -eq 1 ]; then
        awk -F'\t' 'NR>1 && $4=="open" && ($3=="planned" || $3=="active") {print $1}' "$SOURCES_TSV"
    fi
    printf '%s\n' "${ids[@]+"${ids[@]}"}" | sed '/^$/d'
}

raw_dir() { echo "$RIRDB_ROOT/raw/$1"; }

is_archive() {
    case "$1" in
        *.zip|*.z[0-9][0-9]|*.tar|*.tar.gz|*.tgz|*.tbz2|*.tar.bz2|*.tar.xz) return 0 ;;
        *) return 1 ;;
    esac
}

# state_set <id> <key> <json value>: merge one key into $RIRDB_ROOT/state/<id>.json
state_set() {
    local f="$RIRDB_ROOT/state/$1.json" tmp
    mkdir -p "$RIRDB_ROOT/state"
    [ -s "$f" ] || echo '{}' >"$f"
    tmp=$(mktemp "$f.XXXX")
    jq --arg k "$2" --argjson v "$3" '.[$k] = $v' "$f" >"$tmp" && mv "$tmp" "$f"
}

now_json() { printf '"%s"' "$(date -u +%FT%TZ)"; }
