# RH-SYNC Docker V3.2 — Polling sécurisé

Service Docker **sans port entrant**. Il effectue uniquement des connexions HTTPS sortantes vers Grist avec le compte technique RH-SYNC.

## Flux automatisés

- `Cockpit.Team` → `Demandes.Ressources`
- `Demandes.Demandes_RH` → `Cockpit.Demandes_RH`
- décisions `Cockpit.Demandes_RH` → `Demandes.Demandes_RH`
- journalisation dans `Demandes.Journal_Sync`

Le moteur utilise les UUID pour les upserts et ne supprime aucune ligne.

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
