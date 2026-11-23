# V3.9 — clé de synchronisation du planning = Ressource + Date

## Objectif
Éviter les doublons liés à un changement d’ID de ligne dans `Cockpit.Presences` et aligner la synchronisation sur la vraie clé métier du planning.

## Nouvelle règle
La clé d’upsert de `PLANNING_PRESENCE` est désormais :

`Ressource` locale + `Date` normalisée (`YYYY-MM-DD`).

`Source_Presence_ID` / `Source_Feuille_ID` reste renseigné pour la traçabilité mais n’est plus utilisé comme clé de synchronisation.

## Comportement
- CREATE si aucune ligne locale n’existe pour la clé.
- UPDATE si une ligne existe déjà.
- DEDUP si plusieurs lignes locales existent pour la même clé dans la période synchronisée.
- DELETE si une clé locale de la période n’existe plus dans Cockpit.
- CONFLIT_SOURCE si Cockpit contient plusieurs lignes pour la même Ressource+Date : aucune ligne n’est choisie arbitrairement et la valeur locale est préservée.

## Fichiers modifiés
- `app/sync_engine.py`
- `app/runner.py`
- `README.md`

## Fichier ajouté
- `CORRECTIF_V3_9.md`
