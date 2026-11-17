# RH-SYNC V3.7 — Correction de Team.equipe

## Cause confirmée dans les journaux V3.6

L'API Grist renvoie `Team.equipe` (minuscule) avec des références telles que `3` et `1`. La version précédente utilisait `Team.Equipe` (majuscule), et concluait à tort que toutes les équipes étaient vides.

## Correction

- Lecture prioritaire de la colonne technique `Team.equipe`, avec repli sur `Team.Equipe` si nécessaire.
- Résolution de la valeur comme identifiant de `Team_ref` ou, si nécessaire, comme libellé unique.
- Lors de la création d'une demande, renseignement de `Demandes_RH.Equipe`.
- Rattrapage des demandes existantes avec `Equipe` vide seulement, sans écraser les valeurs présentes.
- Cohérence des notifications aux managers avec la même colonne technique.
- Conservation des journaux horodatés, notifications SMTP et autres flux existants.

## Déploiement

Ne pas écraser le fichier `.env` sur le serveur. Depuis le dossier contenant `docker-compose.yml` :

```bash
docker compose up -d --build
docker compose logs --tail=150 -f rh-sync
```

Le premier cycle doit afficher des lignes `RATTRAPAGE ... action=CORRIGEE` et `rattrapage_equipes.updated` supérieur à 0 si les références sont valides et si les droits d'écriture le permettent. Le cycle suivant doit indiquer `updated: 0` et `already_set` augmenté.
