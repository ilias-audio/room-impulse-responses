#!/bin/bash
# Resolve dataset sources into lock files: registry/locks/<id>.lock.tsv
# (relpath, url, size, algo, checksum, provider_version, resolved_at).
#
#   fetch/resolve.sh --wave 0            # all open datasets of wave 0
#   fetch/resolve.sh ace rochester       # specific datasets
#
# Checksums come from the provider (Zenodo md5, DepositOnce MD5, figshare md5).
# Plain HTTP / GitHub sources are trust-on-first-use: checksum "-" until the
# first successful fetch records a sha256. Re-resolving keeps recorded sha256s
# and warns loudly if a provider checksum changed.

source "$(dirname "${BASH_SOURCE[0]}")/lib_common.sh"

# Datasets drawing on several records get record-prefixed paths (files with the
# same name, e.g. Documentation.pdf, exist in more than one record).
rel_for() { # record name
    if [ "$(split_list "$D_RECORDS" | wc -l)" -gt 1 ]; then echo "${1:0:8}/$2"; else echo "$2"; fi
}

emit() { # relpath url size algo checksum version
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$6" "$RESOLVED_AT"
}

resolve_zenodo() {
    local rec json latest
    for rec in $(split_list "$D_RECORDS"); do
        json=$(curl_json "https://zenodo.org/api/records/$rec")
        latest=$(curl_json "https://zenodo.org/api/records/$rec/versions/latest" | jq -r '.id' || echo "?")
        if [ "$latest" != "$rec" ] && [ "$latest" != "?" ]; then
            log "WARN $D_ID: zenodo record $rec has a newer version $latest (pinned to $rec)"
        fi
        jq -r --arg rec "$rec" '.files[] | [.key, .links.self, (.size|tostring), .checksum, "zenodo:\($rec)"] | @tsv' <<<"$json" \
        | while IFS=$'\t' read -r key url size checksum version; do
            selected "$key" || continue
            emit "$(rel_for "$rec" "$key")" "$url" "$size" "${checksum%%:*}" "${checksum#*:}" "$version"
        done
    done
}

resolve_depositonce() {
    local item api=https://api-depositonce.tu-berlin.de/server/api b
    for item in $(split_list "$D_RECORDS"); do
        for b in $(curl_json "$api/core/items/$item/bundles" | jq -r '._embedded.bundles[] | select(.name=="ORIGINAL") | .uuid'); do
            curl_json "$api/core/bundles/$b/bitstreams?size=500" \
            | jq -r --arg item "$item" --arg api "$api" '._embedded.bitstreams[]
                  | [.name, "\($api)/core/bitstreams/\(.uuid)/content", (.sizeBytes|tostring),
                     (.checkSum.checkSumAlgorithm|ascii_downcase), .checkSum.value, "depositonce:\($item)"] | @tsv' \
            | while IFS=$'\t' read -r name url size algo checksum version; do
                selected "$name" || continue
                emit "$(rel_for "$item" "$name")" "$url" "$size" "$algo" "$checksum" "$version"
            done
        done
    done
}

resolve_figshare() {
    local art
    for art in $(split_list "$D_RECORDS"); do
        curl_json "https://api.figshare.com/v2/articles/$art" \
        | jq -r --arg art "$art" '. as $a | .files[] | [.name, .download_url, (.size|tostring), "md5", .computed_md5, "figshare:\($art):v\($a.version)"] | @tsv' \
        | while IFS=$'\t' read -r name url size algo checksum version; do
            selected "$name" || continue
            emit "$(rel_for "$art" "$name")" "$url" "$size" "$algo" "$checksum" "$version"
        done
    done
}

resolve_http() {
    local url name
    for url in $(split_list "$D_URLS"); do
        name=$(urldecode "$(basename "${url%%\?*}")")
        selected "$name" || continue
        emit "$name" "$url" "$(http_size "$url")" "sha256" "-" "$(http_version "$url")"
    done
}

resolve_github() {
    local spec repo ref sha
    for spec in $(split_list "$D_RECORDS"); do
        repo=${spec%@*}; ref=${spec#*@}
        sha=$(curl_json "https://api.github.com/repos/$repo/commits/$ref" | jq -r '.sha')
        [ -n "$sha" ] && [ "$sha" != null ] || die "$D_ID: cannot resolve $spec"
        emit "${repo//\//_}-${sha:0:12}.tar.gz" "https://codeload.github.com/$repo/tar.gz/$sha" "-" "sha256" "-" "github:$repo@$sha"
    done
}

resolve_wget_mirror() {
    local url
    for url in $(split_list "$D_URLS"); do
        # The mirror has no archive; the file manifest written after the
        # mirror becomes the checksum record (trust on first use).
        emit "@mirror" "$url" "-" "manifest" "-" "$(http_version "$url")"
    done
}

# Keep sha256 values recorded on first fetch; warn on changed provider checksums.
merge_with_old() {
    local new=$1 old=$2
    [ -f "$old" ] || { cat "$new"; return; }
    awk -F'\t' -v OFS='\t' -v id="$D_ID" '
        FNR==NR { if (FNR>1) { oldsum[$1 FS $2]=$5; oldalgo[$1 FS $2]=$4 } ; next }
        FNR==1 { print; next }
        {
            k = $1 FS $2
            if ($5 == "-" && (k in oldsum) && oldsum[k] != "-") { $4 = oldalgo[k]; $5 = oldsum[k] }
            else if ($5 != "-" && (k in oldsum) && oldsum[k] != "-" && oldsum[k] != $5 && $4 == oldalgo[k])
                printf("WARN %s: provider checksum changed for %s (%s -> %s)\n", id, $1, oldsum[k], $5) > "/dev/stderr"
            print
        }' "$old" "$new"
}

resolve_one() {
    load_row "$1"
    case "$D_ACCESS/$D_STATUS" in
        open/planned|open/active) ;;
        *) log "skip $D_ID ($D_ACCESS/$D_STATUS)"; return 0 ;;
    esac
    RESOLVED_AT=$(date -u +%FT%TZ)
    local tmp out="$LOCKS_DIR/$D_ID.lock.tsv"
    mkdir -p "$LOCKS_DIR"
    tmp=$(mktemp "$out.XXXX")
    {
        echo "$LOCK_HEADER"
        case "$D_KIND" in
            zenodo) resolve_zenodo ;;
            depositonce) resolve_depositonce ;;
            figshare) resolve_figshare ;;
            http) resolve_http ;;
            github) resolve_github ;;
            wget_mirror) resolve_wget_mirror ;;
            *) die "$D_ID: source kind '$D_KIND' not implemented yet" ;;
        esac
    } >"$tmp"
    local n; n=$(($(wc -l <"$tmp") - 1))
    [ "$n" -gt 0 ] || { rm -f "$tmp"; die "$D_ID: resolved 0 files (check include globs)"; }
    # duplicate relpaths across records would collide on disk
    if cut -f1 "$tmp" | sort | uniq -d | grep -q .; then
        rm -f "$tmp"; die "$D_ID: duplicate file names across records"
    fi
    merge_with_old "$tmp" "$out" >"$tmp.merged" && mv "$tmp.merged" "$out" && rm -f "$tmp"
    local bytes; bytes=$(awk -F'\t' 'NR>1 && $3!="-" {s+=$3} END{printf "%.0f", s}' "$out")
    log "resolved $D_ID: $n files, $(numfmt --to=iec "$bytes" 2>/dev/null || echo "$bytes B") known size"
    state_set "$D_ID" resolved_at "$(now_json)"
}

main() {
    local ids; ids=$(ids_from_args "$@")
    [ -n "$ids" ] || die "no datasets selected (use --wave N, --all, or ids)"
    local id
    for id in $ids; do resolve_one "$id"; done
}

main "$@"
