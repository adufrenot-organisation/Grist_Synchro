# V3.10 — propagation du booléen AutoValidation

Cette version ajoute uniquement le transport de `Demandes_RH.AutoValidation` du document Collab vers le document Cockpit.

## Règles

- `AutoValidation=false` côté Collab → `false` côté Cockpit.
- `AutoValidation=true` côté Collab → `true` côté Cockpit.
- Une modification du booléen est détectée même si les autres champs de la demande sont inchangés.
- Aucune auto-validation n’est exécutée par RH-SYNC V3.10.
- Le statut est transporté selon les règles existantes ; le workflow de décision Cockpit reste inchangé.
- Les règles V3.9 de synchronisation du planning par `Ressource + Date` sont conservées.
