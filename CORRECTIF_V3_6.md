# RH-SYNC V3.6 — Journal de diagnostic détaillé

En plus de l'horodatage V3.5, chaque étape présente un bilan. Pour les demandes dont l'équipe est introuvable, le journal affiche le demandeur Team, la valeur brute et le type Python de `Team.Equipe`, les champs techniques semblables à Equipe, la liste des identifiants techniques renvoyés par Grist si `Equipe` est vide, le résultat de la résolution et l'action effectuée.

Le rattrapage détaille les demandes corrigées, déjà renseignées ou en anomalie, avec un bilan de fin. Les modifications de Ressources et Demandes sont également tracées. Les valeurs sensibles d'email/API sont exclues des nouveaux diagnostics.

Une colonne dont le titre visible est « Equipe » peut porter un identifiant technique différent. Les lignes `DIAGNOSTIC ... colonnes_disponibles` servent à repérer précisément ce cas, sans modifier automatiquement le schéma Grist.

La table `Journal_Sync` conserve les 12 000 derniers caractères de détails (comportement hérité). Pour le journal complet, consulter `docker compose logs --timestamps -f rh-sync`.
