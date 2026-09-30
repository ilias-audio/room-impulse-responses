#!/bin/bash
#SBATCH -p computeshort
#SBATCH -t 0:10:0
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=1G
#SBATCH -o qlogs/net_%j.out
#SBATCH -e qlogs/net_%j.err

# Does a compute node have outbound internet? (No Python.)
#   sbatch jobs/net_probe.sh ; cat qlogs/net_<JOBID>.out

echo "host: $(hostname)"
env | grep -i proxy || echo "no proxy vars"
for u in https://zenodo.org/api/records/6408611 \
         https://api-depositonce.tu-berlin.de/server/api \
         https://api.figshare.com/v2/articles/26801089 \
         https://huggingface.co/api/datasets/treble-technologies/Treble10-RIR \
         https://webfiles.york.ac.uk/OPENAIR/IRs/ \
         https://conda.anaconda.org/conda-forge/ \
         https://pypi.org/simple/pyrato/; do
    code=$(curl -s -o /dev/null -m 20 -w "%{http_code} %{time_total}s" "$u" || echo "FAIL")
    echo "$code  $u"
done
echo "--- 100 MB ranged speed test (zenodo) ---"
curl -s -o /dev/null -m 120 -r 0-104857599 -L -w "%{http_code} %{size_download}B %{speed_download}B/s\n" \
    "https://zenodo.org/records/6985104/files/IR_Arni_upload_numClosed_0-5.zip?download=1" || echo "speed test FAIL"
which jq unzip zip tar bzip2 md5sum sha256sum
