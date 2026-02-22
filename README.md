# plexctl (mini CLI Plex)

Petit outil CLI **sans dépendance externe** (Python 3 stdlib) pour piloter Plex en local sur le NAS via:

- **Plex Media Server URL Commands** (HTTP sur `http://127.0.0.1:32400`)
- commandes Docker locales (`docker logs`, `docker restart`, `docker exec`)

## Pré-requis

- Python 3
- Docker CLI (`docker`) sur le NAS
- Plex tourne en Docker (par défaut `container_name=plex`)

## Installation rapide

1) Aller dans le dossier du projet:

```bash
cd /srv/docker/plex/plexctl  # adapte au chemin réel sur ton NAS
```

2) Créer `.env`:

```bash
cp .env.example .env
```

3) Éditer `.env` et renseigner ton token:

- `PLEX_BASE_URL` (par défaut `http://127.0.0.1:32400`)
- `PLEX_TOKEN` (obligatoire)
- `PLEX_CONTAINER` (par défaut `plex`)

4) (Optionnel) rendre le script exécutable:

```bash
chmod +x plexctl.py
```

## Exemples CLI

Lister les bibliothèques:

```bash
python3 plexctl.py sections
python3 plexctl.py sections --json
```

Rafraîchir une section:

```bash
python3 plexctl.py refresh --section 1
python3 plexctl.py refresh --section 1 --force
```

Rafraîchir un chemin précis (après un download, par ex.):

```bash
python3 plexctl.py refresh --section 1 --path "/srv/media/Movies/New Movie (2026)"
```

Logs / restart:

```bash
python3 plexctl.py logs -n 200
python3 plexctl.py restart
```

Scanner (dans le conteneur):

```bash
python3 plexctl.py scanner --list
```

## VS Code Tasks

Dans VS Code (Remote-SSH), ouvre le dossier `Plex/plexctl/` comme dossier de travail, puis:

- `Terminal → Run Task`
- Choisis une tâche **Plex: ...**

Les tâches sont définies dans `.vscode/tasks.json` et appellent:

- `python3 ${workspaceFolder}/plexctl.py ...`

## Notes sécurité

- Le token n’est **jamais** hardcodé.
- Ne commit jamais `.env` (il est ignoré via `.gitignore`).
- Le script masque le token (`****`) quand il affiche une URL.
