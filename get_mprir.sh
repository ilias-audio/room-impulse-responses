#!/bin/bash

dest=$1
mp_rir_dir="$dest/MP-RIR"
zip_file="$dest/MP-RIR_Dataset.zip"
zenodo_url="https://zenodo.org/api/records/11148712/files-archive?download=1"

# download data
echo "Downloading MP-RIR Dataset..."
wget --progress=bar:force:noscroll -O "$zip_file" "$zenodo_url"
# curl -L --progress-bar --output "$zip_file" "$zenodo_url"

# extract data
mkdir -p "$mp_rir_dir"
unzip -q "$zip_file" -d "$mp_rir_dir"

# delete zip file after extraction
rm -f "$zip_file"

echo "Download finished."