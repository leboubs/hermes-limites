# Limites — widget Hermes Desktop

Widget compact pour **Hermes Desktop** : quotas d'abonnement Claude, Codex et
OpenCode Go, plus le plafond de clé et la dépense OpenRouter du jour.

Il s'affiche à deux endroits :

- un **item de barre d'état** — `C 88% · X 62% · Go 0% · OR $1.66/10` ;
- un **panneau « limites »** (à droite) avec une jauge par fenêtre et l'heure de
  reset.

## Installation

Dans Hermes Desktop : **Capabilities → Plugins → Install from Git**, ou ouvre
directement ce lien :

```
hermes://plugin/install?repo=leboubs/hermes-limites
```

Coche la composante **Desktop** (l'interface). La composante agent n'est utile
que si tu veux aussi le backend sur une autre machine. Rien ne s'installe sans
confirmation. Après installation, ⌘K → **Reload desktop plugins** si le widget
n'apparaît pas tout de suite.

## Comment il lit les chiffres

Tout est collecté côté serveur, dans le processus passerelle, par
`dashboard/plugin_api.py` (route `/api/plugins/limites/data`, cache 45 s). Le
panneau ne fait qu'afficher ce que le backend a répondu : aucun chiffre n'est
calculé dans l'interface, et aucun jeton ne descend dans la page.

| Source | Endpoint | Identifiant utilisé |
|---|---|---|
| Claude | `api.anthropic.com/api/oauth/usage` | `~/.claude/.credentials.json` (OAuth abonnement) |
| Codex | `chatgpt.com/backend-api/codex/usage` | `~/.codex/auth.json` (connexion ChatGPT) |
| OpenCode Go | `opencode.ai/zen/go/v1/usage` | `OPENCODE_GO_API_KEY` (`.env` Hermes) |
| OpenRouter | `/api/v1/key`, `/api/v1/credits` + `state.db` | `OPENROUTER_API_KEY` (`.env` Hermes) |

La dépense OpenRouter du jour est la somme estimée des appels de la journée dans
la table `session_model_usage` de `state.db` (profil Hermes courant) ; le
plafond et la consommation hebdomadaire viennent de la clé elle-même.

Chaque source est isolée : si l'une tombe (jeton expiré, réseau), les autres
s'affichent et la tuile concernée indique l'erreur.

## Limites connues

- Le panneau s'appuie sur `ctx.rest('/data')` : la composante **agent** doit être
  installée et activée sur l'hôte qui sert la passerelle (`hermes plugins enable
  limites`).
- Les fenêtres varient selon l'offre : Codex n'expose qu'une fenêtre
  hebdomadaire sur le plan Plus ; un plan Pro en ajoute une secondaire.
- Pas de secrets dans ce dépôt : les clés sont lues sur la machine, à l'exécution.
