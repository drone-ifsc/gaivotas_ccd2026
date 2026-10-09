#!/usr/bin/env python3
"""rqt_bag que publica os topicos do bag ao dar Play.

No rqt_bag padrao o Play so move o cursor: nada e publicado ate fazer
botao direito -> Publish -> Publish All, e nao existe opcao de linha de comando
para isso. Este wrapper liga a publicacao de todos os topicos sempre que o Play
e acionado (botao ou barra de espaco).

Uso: mesmos argumentos do rqt_bag (ex.: --clock voo.bag). Um argumento que seja
uma pasta e trocado pelo .bag mais recente dela.
"""
import glob
import os
import sys

from rqt_bag.bag import Bag
from rqt_bag.bag_timeline import BagTimeline
from rqt_gui.main import Main

_orig_set_play_speed = BagTimeline._set_play_speed


def _set_play_speed(self, play_speed):
    # Chamado na thread da GUI (botao/tecla), como o item de menu Publish All.
    if play_speed > 0.0:
        self.set_publishing_state(True)
    _orig_set_play_speed(self, play_speed)


BagTimeline.play_speed = property(BagTimeline._get_play_speed, _set_play_speed)


def newest_bag(path):
    """Pasta -> .bag mais recente dela; qualquer outro argumento volta como veio."""
    if not os.path.isdir(path):
        return path
    bags = glob.glob(os.path.join(path, '*.bag'))
    if not bags:
        sys.exit("Nenhum .bag em %s" % path)
    return max(bags, key=os.path.getmtime)


if __name__ == '__main__':
    sys.argv[1:] = [newest_bag(a) for a in sys.argv[1:]]
    plugin = 'rqt_bag.bag.Bag'
    main = Main(filename=plugin)
    sys.exit(main.main(standalone=plugin, plugin_argument_provider=Bag.add_arguments))
