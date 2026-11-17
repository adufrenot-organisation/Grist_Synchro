# RH-SYNC Docker V3.5 — Journaux horodatés

Sur la base de la V3.4, sans modifier les règles métiers ni le rattrapage des équipes.

- `runner.py` : événements Docker préfixés par date/heure et fuseau.
- `sync_engine.py` : chaque message `details` porte son propre horodatage et niveau `[INFO]`, `[AVERTISSEMENT]` ou `[ERREUR]`.
- `Journal_Sync.Details` : contient les mêmes messages horodatés.
- Résultat JSON de chaque cycle : `timestamp` et `started_at`.
- Fuseau `RH_SYNC_TIMEZONE` (défaut `Europe/Paris`), tzdata installé dans l'image Docker pour gérer heure d'été/hiver.
- `Journal_Sync.Date_Sync` reste inchangé (timestamp epoch Grist).
- Aucun `.env` réel ni état applicatif inclus. Volume Docker conservé.

## Déploiement

Conserver `.env` sur le serveur, remplacer les fichiers de l'application, puis exécuter :

```bash
docker compose up -d --build
docker compose logs -f --tail=100 rh-sync
```

Les journaux Docker natifs restent accessibles via `docker compose logs --timestamps`.
