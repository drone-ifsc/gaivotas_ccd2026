#!/usr/bin/env bash
# Baixa um rosbag do drone por SFTP, usando as chaves SSH já configuradas (ssh-copy-id).
#
# Uso:
#   fetch_rosbag.sh [usuario@host:]<caminho_remoto> [pasta_local]
#
#   <caminho_remoto>  arquivo .bag / .bag.active, ou uma pasta -> baixa o mais recente dela
#                     (inclusive um .bag.active).
#                     Absoluto, ou relativo ao home remoto (sem "~": o shell local o expande).
#   [pasta_local]     destino (default: pasta atual)
#
# Host default: $DRONE_HOST, ou falcon@192.168.0.105.
# Download interrompido continua de onde parou ao rodar o mesmo comando de novo.
#
# .bag.active (gravação interrompida, sem índice) é reindexado com "rosbag reindex" e salvo
# como .bag normal, sem o .active. Usa o rosbag do sistema se houver; senão roda num
# container descartável da imagem $ROS_IMAGE (default droneifsc/ros-noetic:x86).
#
# Exemplos:
#   fetch_rosbag.sh catkin_ws/src/gaivotas_ccd2026/a10_gaivotas_ccd2026/rosbags
#   fetch_rosbag.sh /home/falcon/voo.bag ~/bags
#   fetch_rosbag.sh root@10.0.0.5:/data/a11_2026-10-09-11-30-00.bag
#   ./fetch_rosbag.sh /home/falcon/catkin_ws/src/gaivotas_ccd2026/a10_gaivotas_ccd2026/rosbags ~/catkin_ws/src/gaivotas_ccd2026/a10_gaivotas_ccd2026/rosbags

set -euo pipefail

DRONE_HOST="${DRONE_HOST:-falcon@192.168.0.105}"
ROS_IMAGE="${ROS_IMAGE:-droneifsc/ros-noetic:x86}"
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

# Reindexa <pasta>/<X.bag.active> e salva como <pasta>/<X.bag>. A saída vai para uma pasta
# temporária: o .active baixado só é apagado se o reindex der certo.
reindex_active() {
    local dir name tmp
    dir="$(cd "$1" && pwd)"
    name="$2"
    tmp=".reindex_$$"
    mkdir -p "$dir/$tmp"
    echo "Reindexando $name ..."
    if command -v rosbag >/dev/null; then
        (cd "$dir" && rosbag reindex --output-dir="$tmp" "$name") || true
    elif command -v docker >/dev/null; then
        docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$dir:/bags" -w /bags "$ROS_IMAGE" \
            bash -c 'source /opt/ros/noetic/setup.bash && rosbag reindex --output-dir="$0" "$1"' "$tmp" "$name" || true
    fi
    if [ ! -s "$dir/$tmp/$name" ]; then
        rm -rf "${dir:?}/$tmp"
        echo "Falha ao reindexar (precisa de rosbag ou docker com $ROS_IMAGE); o download ficou em $dir/$name" >&2
        exit 1
    fi
    touch -r "$dir/$name" "$dir/$tmp/$name"     # mantém a data da gravação
    mv "$dir/$tmp/$name" "$dir/${name%.active}"
    rm "$dir/$name"
    rmdir "$dir/$tmp"
    echo "Salvo como $dir/${name%.active}"
}

# Pasta -> rosbag mais recente (ls -1t ordena por data), inclusive .bag.active.
if [[ "$remote" != *.bag && "$remote" != *.bag.active ]]; then
    dir="${remote%/}"
    listing="$(sftp "${SFTP_OPTS[@]}" -b - "$DRONE_HOST" <<< "ls -1t \"$dir\"/*.bag*")" || {
        echo "Não foi possível listar os .bag em $DRONE_HOST:$dir" >&2
        exit 1
    }
    remote="$(awk '!/^sftp>/ && /\.bag(\.active)?$/ {print; exit}' <<< "$listing")"
    if [ -z "$remote" ]; then
        echo "Nenhum .bag em $DRONE_HOST:$dir" >&2
        exit 1
    fi
fi

name="$(basename "$remote")"
if [[ "$name" == *.active && -e "$local_dir/${name%.active}" ]]; then
    echo "$local_dir/${name%.active} já existe (reindexado antes); apague-o para baixar de novo"
    exit 0
fi

mkdir -p "$local_dir"
echo "Baixando $DRONE_HOST:$remote -> $local_dir/"
# -a retoma download parcial, -p preserva a data. O sftp monta um "get" interno sem
# aspas, então espaços nos caminhos precisam ir escapados.
sftp "${SFTP_OPTS[@]}" -a -p "$DRONE_HOST:${remote// /\\ }" "${local_dir// /\\ }/"

if [[ "$name" == *.active ]]; then
    reindex_active "$local_dir" "$name"
fi
