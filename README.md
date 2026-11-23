# RH-SYNC Docker V3.10 — Ressources, demandes et planning de présence

Service Docker **sans port entrant**. Il effectue uniquement des connexions HTTPS sortantes vers Grist avec le compte technique RH-SYNC.

## Flux automatisés

- `Cockpit.Team` → `Demandes.Ressources`, avec synchronisation du nom d'équipe depuis `Team_ref.libelle` vers `Ressources.Equipe_Code` ;
- `Demandes.Demandes_RH` → `Cockpit.Demandes_RH` ;
- décisions `Cockpit.Demandes_RH` → `Demandes.Demandes_RH` ;
- après une validation, relecture ciblée de `Cockpit.Presences` pour la ressource et la période concernées ;
- `Cockpit.Presences` → `Demandes.PLANNING_PRESENCE` ;
- consommation des lignes `EN_ATTENTE` de `Demandes.DEMANDES_SYNCHRO` ;
- création automatique d'une demande de synchro complète de l'année selon `Demandes.PARAM_SYNCHRO` ;
- journalisation dans `Demandes.Journal_Sync`.

Les flux historiques restent idempotents par UUID. `PLANNING_PRESENCE` est une table esclave : lors d'une synchro de période, le moteur crée/met à jour les présences et supprime les lignes source disparues dans cette période.

## Installation

Prérequis : Docker Engine + Docker Compose v2, et accès HTTPS **sortant** du serveur vers votre instance Grist.

```bash
unzip RH_SYNC_Docker_V3_0_Polling.zip
cd RH_SYNC_Docker_V3_0_Polling
cp .env.example .env
nano .env
```

Renseigner dans `.env` :

- `GRIST_HOST`
- `RH_SYNC_API_KEY` : clé du compte technique RH-SYNC
- `DEMANDES_DOC_ID`
- `COCKPIT_DOC_ID`
- `SYNC_INTERVAL_SECONDS=60`

Ne partagez jamais le fichier `.env` et ne mettez pas la clé dans Grist ou dans un widget.

Démarrage :

```bash
./install.sh
```

Ou manuellement :

```bash
docker compose build
docker compose up -d
```

## Vérification

```bash
docker compose ps
docker compose logs -f rh-sync
```

Le conteneur doit apparaître `Up` / `healthy`. Un cycle est exécuté immédiatement au démarrage puis toutes les 60 secondes par défaut.

## Test unique avant fonctionnement permanent

```bash
./run-once.sh
```

## Arrêt / redémarrage / mise à jour

```bash
docker compose stop
docker compose restart rh-sync
docker compose down
docker compose up -d --build
```

## Sécurité

- aucun `ports:` dans Compose ; le conteneur n'écoute pas Internet ;
- aucune URL publique requise ;
- trafic uniquement sortant vers Grist ;
- clé API uniquement dans `.env` sur le serveur Docker ;
- utilisateur non-root dans le conteneur ;
- capabilities Linux supprimées et `no-new-privileges` activé ;
- le compte technique doit conserver les ACL minimales nécessaires dans les deux documents.

## Important avant production

Cette V3.2 Dockerise le moteur de synchronisation déjà utilisé pour vos tests. Après installation, lancez d'abord `./run-once.sh`, contrôlez `Journal_Sync`, `Ressources` et une demande de test complète avant de laisser le polling permanent.

## Notifications email SMTP — V3.2

Le service peut notifier automatiquement :

- le ou les **managers actifs** lorsqu'une nouvelle demande est créée dans le Cockpit ;
- le **demandeur** lorsqu'un statut de décision change (`VALIDE`, `REFUSE`, etc.).

Les managers sont résolus via `Cockpit.Managers_Equipes`. Le moteur utilise `Manager_Email` s'il est renseigné, sinon l'email du `Manager` référencé dans `Cockpit.Team`. L'email du demandeur vient de la ressource locale synchronisée.

Dans `.env` :

```env
SMTP_ENABLED=true
SMTP_HOST=smtp.example.fr
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USER=compte-smtp@example.fr
SMTP_PASSWORD=mot_de_passe_ou_secret
SMTP_FROM=rh@example.fr
SMTP_FROM_NAME=RH - Demandes
SMTP_TIMEOUT_SECONDS=20

# Optionnels : ajoutés dans les messages
PORTAL_URL=https://...
COCKPIT_URL=https://...
```

`SMTP_SECURITY` accepte `starttls`, `ssl` ou `none`. Pour STARTTLS, le port usuel est 587 ; pour SMTP SSL direct, généralement 465.

Les erreurs SMTP sont journalisées mais **ne bloquent pas la synchronisation RH**. Les emails sont déclenchés sur événement métier détecté : création d'une nouvelle demande pour le manager, changement de statut pour le demandeur. Le polling ne renvoie donc pas le même email à chaque cycle.


## Notifications métier V3.2

Les emails sont envoyés **uniquement après une synchronisation réussie**.

- Création portail → Cockpit : confirmation au demandeur + information au(x) manager(s).
- Modification portail → Cockpit : confirmation au demandeur + information au(x) manager(s).
- Modification manager/Cockpit → portail : information au demandeur + confirmation au manager.
- Les changements de statut, commentaire manager et date de décision sont inclus dans la détection.
- Anti-doublon persistant : les empreintes sont stockées dans `/data/state.json`, monté dans le volume Docker `rh_sync_state`.
- `NOTIFY_EXISTING_ON_FIRST_RUN=false` évite d'envoyer des mails pour toutes les anciennes demandes lors du premier démarrage.
- Une erreur SMTP est journalisée mais ne bloque jamais la synchronisation Grist.

Important : le manager est résolu via `Managers_Equipes` pour les notifications venant du portail. Pour une modification côté Cockpit, la confirmation est envoyée au manager porté par la demande.


## Planning de présence et synchronisation pilotée — V3.8

### Tables attendues côté document Demandes / Collab

`PLANNING_PRESENCE` doit contenir au minimum :

- `Ressource` (Ref vers `Ressources`) ;
- `Date` ;
- `Motif_Code` ;
- `Statut` ;
- `Equipe_Code` ;
- `Derniere_Sync` ;
- `Erreur_Sync` ;
- une clé source : **`Source_Presence_ID` ou `Source_Feuille_ID`**.

Le moteur accepte les deux noms de clé source. Si `Libelle`, `Commentaire` ou `Source` existent, ils sont également alimentés.

`DEMANDES_SYNCHRO` doit contenir : `Date_Debut`, `Date_Fin`, `Type_Synchro`, `Statut`, `Demandee_Par`, `Date_Demande`, `Date_Debut_Execution`, `Date_Fin_Execution`, `Nb_Lignes_Lues`, `Nb_Lignes_Creees`, `Nb_Lignes_MAJ`, `Nb_Erreurs`, `Message`, `Force_Full`.

Une ligne `Statut=EN_ATTENTE` est prise en charge automatiquement. Le moteur la passe à `EN_COURS`, synchronise la période, puis la termine en `TERMINEE` ou `ERREUR`.

### Paramètres hebdomadaires dans `PARAM_SYNCHRO`

Valeurs reconnues :

- `SYNC_HEBDO_ACTIF` : `true` / `false` ;
- `SYNC_HEBDO_JOUR` : `LUNDI` à `DIMANCHE` ;
- `SYNC_HEBDO_HEURE` : heure locale `HH:MM` ;
- `SYNC_HEBDO_PERIODE` : actuellement `ANNEE_EN_COURS` ;
- `SYNC_AUTO_VALIDATION_ACTIF` : `true` / `false`.

Avec les valeurs par défaut du portail (`DIMANCHE`, `22:00`), le premier cycle de polling exécuté le dimanche à partir de 22:00 crée une demande `HEBDO_ANNUELLE` couvrant du 1er janvier au 31 décembre de l'année en cours. Une clé persistante dans `/data/state.json` évite de la recréer plusieurs fois pendant la même semaine.

### Validation d'une demande

Quand une demande revient du Cockpit avec un statut validé/accepté, le moteur met à jour la demande locale puis relit `Cockpit.Presences` sur `Date_Debut` → `Date_Fin`, uniquement pour le `UUID_Ressource` concerné. Le code et le libellé du motif viennent de `Cockpit.Motifs_RH`, ce qui garantit que le planning Collab reflète le motif réellement enregistré dans le Cockpit.

### Première mise en service

Depuis Administration → Demandes de synchro dans le portail Collab, utiliser **Toute l'année en cours**, conserver `Force_Full=true`, puis déposer la demande. Au cycle suivant de RH-SYNC, elle doit passer `EN_ATTENTE → EN_COURS → TERMINEE`.



## V3.10 — propagation AutoValidation

- La colonne booléenne `Demandes_RH.AutoValidation` est désormais propagée de Collab vers Cockpit.
- La valeur fait partie de l’empreinte de synchronisation : un changement `false ↔ true` déclenche une mise à jour Cockpit même si aucun autre champ de la demande ne change.
- Cette version **ne déclenche aucune validation automatique** : Cockpit reçoit seulement le booléen et la demande reste dans son workflow normal.
- La V3.9 reste incluse : clé métier du planning = `Ressource + Date`.

## V3.9 — clé métier du planning

La synchronisation `Cockpit.Presences -> PLANNING_PRESENCE` utilise désormais comme clé d'upsert le couple **Ressource locale + Date**. `Source_Presence_ID` (ou `Source_Feuille_ID`) est conservé uniquement comme information de traçabilité.

Règles :
- 0 ligne cible pour `Ressource+Date` : création ;
- 1 ligne cible : mise à jour depuis Cockpit ;
- plusieurs lignes cibles : conservation d'une ligne et suppression des doublons dans la période synchronisée ;
- plusieurs lignes `Cockpit.Presences` pour la même `Ressource+Date` : conflit source journalisé, aucune valeur n'est choisie arbitrairement ;
- lors d'une réconciliation, une clé locale absente du Cockpit est supprimée, sauf si la clé est en conflit côté Cockpit.

`Cockpit.Presences` reste la source maître du planning.
