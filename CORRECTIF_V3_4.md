# RH-SYNC V3.4 — équipes des demandes

- Création et modification : renseigne Demandes_RH.Equipe depuis Team.Equipe si la demande n’a pas déjà une équipe.
- Rattrapage à chaque cycle : complète les demandes historiques dont Equipe est vide.
- Team.Equipe : accepte ID de référence Grist ou libellé issu de Team_ref.libelle.
- Correspondance des libellés sans distinction de casse, espaces extérieurs ignorés.
- Refuse les libellés ambigus ou introuvables et journalise les avertissements.
- Ne remplace jamais une équipe déjà renseignée.
- Conserve les flux et SMTP existants.
- .env volontairement exclu : conserver celui du serveur.
