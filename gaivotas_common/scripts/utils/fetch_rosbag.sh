#!/usr/bin/env bash
# Baixa um rosbag do drone por SFTP, usando as chaves SSH já configuradas (ssh-copy-id).
#
# Uso:
#   fetch_rosbag.sh [usuario@host:]<caminho_remoto> [pasta_local]
#
#   <caminho_remoto>  arquivo .bag, ou uma pasta -> baixa o .bag mais recente dela.
#                     Absoluto, ou relativo ao home remoto (sem "~": o shell local o expande).
#   [pasta_local]     destino (default: pasta atual)
#
# Host default: $DRONE_HOST, ou falcon@192.168.0.105.
# Download interrompido continua de onde parou ao rodar o mesmo comando de novo.
#
# Exemplos:
#   fetch_rosbag.sh catkin_ws/src/gaivotas_ccd2026/a10_gaivotas_ccd2026/rosbags
#   fetch_rosbag.sh /home/falcon/voo.bag ~/bags
#   fetch_rosbag.sh root@10.0.0.5:/data/a11_2026-10-09-11-30-00.bag
#   ./fetch_rosbag.sh /home/falcon/catkin_ws/src/gaivotas_ccd2026/a10_gaivotas_ccd2026/rosbags ~/catkin_ws/src/gaivotas_ccd2026/a10_gaivotas_ccd2026/rosbags

set -euo pipefail

DRONE_HOST="${DRONE_HOST:-falcon@192.168.0.105}"
# BatchMode: só chave, nunca pede senha (falha na hora se a chave não for aceita).
SFTP_OPTS=(-o BatchMode=yes -o ConnectTimeout=10)

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Uso: $(basename "$0") [usuario@host:]<caminho_remoto> [pasta_local]" >&2
    exit 1
fi

remote="$1"
local_dir="${2:-.}"

# Forma host:caminho (dois-pontos antes de qualquer barra).
if [[ "$remote" =~ ^([^/:]+):(.+)$ ]]; then
    DRONE_HOST="${BASH_REMATCH[1]}"
    remote="${BASH_REMATCH[2]}"
fi
remote="${remote#\~/}"

# Pasta -> .bag mais recente (ls -1t ordena por data; *.bag ignora os .bag.active em gravação).
if [[ "$remote" != *.bag && "$remote" != *.bag.active ]]; then
    dir="${remote%/}"
    listing="$(sftp "${SFTP_OPTS[@]}" -b - "$DRONE_HOST" <<< "ls -1t \"$dir\"/*.bag")" || {
        echo "Não foi possível listar os .bag em $DRONE_HOST:$dir" >&2
        exit 1
    }
    remote="$(awk '!/^sftp>/ && /\.bag$/ {print; exit}' <<< "$listing")"
fi

mkdir -p "$local_dir"
echo "Baixando $DRONE_HOST:$remote -> $local_dir/"
# -a retoma download parcial, -p preserva a data. O sftp monta um "get" interno sem
# aspas, então espaços nos caminhos precisam ir escapados.
sftp "${SFTP_OPTS[@]}" -a -p "$DRONE_HOST:${remote// /\\ }" "${local_dir// /\\ }/"
