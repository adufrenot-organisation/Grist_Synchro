# V3.8 — synchronisation équipes et planning de présence

## Ajouts

- synchronisation systématique du nom d'équipe de chaque ressource depuis `Cockpit.Team.equipe` / `Team_ref.libelle` vers `Demandes.Ressources.Equipe_Code` ;
- synchronisation de `Cockpit.Presences` vers `Demandes.PLANNING_PRESENCE` ;
- compatibilité avec `Source_Presence_ID` **ou** `Source_Feuille_ID` ;
- mise à jour ciblée du planning lorsqu'une demande revient validée/acceptée ;
- consommation des demandes `EN_ATTENTE` de `DEMANDES_SYNCHRO` ;
- synchro complète de l'année en cours pilotée par `PARAM_SYNCHRO`, par défaut le dimanche à 22:00 si le paramètre est actif ;
- réconciliation des suppressions du planning dans la période synchronisée ;
- propagation du changement de `Statut` du portail vers le Cockpit lors d'une mise à jour de demande.

## Sécurité / exploitation

- aucun port entrant ajouté ;
- même compte technique et mêmes variables Grist ;
- état hebdomadaire conservé dans `/data/state.json` ;
- toutes les opérations restent journalisées dans `Journal_Sync`.
