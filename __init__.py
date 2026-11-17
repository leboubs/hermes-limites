"""Moitié agent du plugin « limites » : aucune route d'outil ni crochet.

Le travail serveur vit dans dashboard/plugin_api.py (monté par la passerelle sous
/api/plugins/limites/) et l'interface dans ~/.hermes/desktop-plugins/limites.
"""


def register(ctx) -> None:
    """Rien à enregistrer côté agent : le plugin ne fournit ni outil ni crochet.

    Le point d'entrée existe pour que le chargeur ne signale pas un plugin vide ;
    la partie utile est la route /api/plugins/limites/data.
    """
    return None
