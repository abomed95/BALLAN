# Mise en service de BALLAN dans une école

Procédure pour une école cliente, du serveur nu au premier message d'un
parent. Compter une demi-journée technique, plus les délais de Meta
(vérification de l'entreprise, approbation du modèle de rappel : de quelques
heures à quelques jours).

---

## 0. Ce qu'il faut avant de commencer

| Quoi | Qui le fournit |
|---|---|
| Un serveur Linux (2 vCPU, 2 Go de RAM, 20 Go de disque suffisent) avec Docker et le plugin compose | AMD Digital |
| Un nom de domaine dont on peut modifier le DNS, par ex. `ballan.ecole.dj` | école ou AMD Digital |
| Un **numéro de téléphone dédié** à BALLAN, qui n'est pas déjà utilisé sur l'application WhatsApp | école |
| Un compte Meta Business au nom de l'école (vérification d'entreprise) | école |
| La liste des classes, enseignants, créneaux de réception, motifs de rendez-vous | école |
| L'export CSV des élèves et des numéros des parents, **avec le consentement** aux rappels | secrétariat |
| La validation par l'école des textes dans chaque langue activée | école + relecteurs |

> **Consentement et données de mineurs.** Les rappels ne partent qu'aux
> numéros marqués `consentement = oui` dans le CSV. Faire signer à l'école le
> contrat de sous-traitance et informer les familles *avant* l'import.

---

## 1. Côté Meta (WhatsApp Cloud API)

1. Sur [developers.facebook.com](https://developers.facebook.com), créer une
   application de type **Business**, ajouter le produit **WhatsApp**.
2. Ajouter le numéro dédié de l'école et le vérifier. Noter le
   **Phone number ID** (identifiant technique, différent du numéro).
3. Dans *Paramètres de l'application → Base*, noter le **App secret**.
4. Dans *Business Settings → Utilisateurs système*, créer un utilisateur
   système, lui attribuer l'application et le compte WhatsApp, et générer un
   **jeton permanent** avec les droits `whatsapp_business_messaging` et
   `whatsapp_business_management`. *Ne pas utiliser le jeton temporaire de
   24 h affiché sur la page de démarrage.*
5. Créer le **modèle de message de rappel** (catégorie *Utilitaire*), dans
   chaque langue activée, avec trois variables, par exemple en français :

   > Rappel : rendez-vous pour {{1}} le {{2}}, avec {{3}}. Pour annuler,
   > répondez « menu » puis choisissez 2.

   Noter son nom (par ex. `rappel_rdv`). Tant qu'il n'est pas approuvé, les
   rappels ne partent qu'aux parents ayant écrit dans les dernières 24 h.

Le webhook se configure à l'étape 5, une fois le serveur en ligne.

---

## 2. Installer le serveur

```sh
git clone <dépôt> ballan && cd ballan
cp .env.example .env
chmod 600 .env
# Trois secrets, un par ligne :
for i in 1 2 3; do python3 -c "import secrets; print(secrets.token_urlsafe(32))"; done
```

Remplir `.env` :

- `BALLAN_DOMAINE` : le nom de domaine ; créer l'enregistrement DNS `A` vers
  l'IP du serveur **avant** de démarrer (le certificat HTTPS en dépend) ;
- `POSTGRES_PASSWORD`, `BALLAN_ADMIN_TOKEN`, `WHATSAPP_VERIFY_TOKEN` : les
  trois secrets générés ;
- `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` : relevés
  à l'étape 1 ;
- `WHATSAPP_TEMPLATE_RAPPEL` : le nom du modèle ;
- `BALLAN_NUMERO_SECRETARIAT` : le WhatsApp du secrétariat (alerte à chaque
  demande à rappeler) ;
- `BALLAN_ETABLISSEMENT_ID` : laissé vide pour l'instant, rempli à l'étape 3.

Ouvrir les ports 80 et 443 du pare-feu. Aucun autre port n'est exposé.

---

## 3. Charger l'école

Préparer deux fichiers dans `config/` (dossier ignoré par git : ces données
ne doivent jamais entrer dans le dépôt) en partant des modèles :

- `config/ecole.json` ← `exemples/ecole.exemple.json` : établissement, année,
  vacances, niveaux, enseignants et leurs créneaux de réception, classes,
  motifs, fermetures, horaires de Ramadan ;
- `config/familles.csv` ← `exemples/familles.exemple.csv` : une ligne par
  élève, jusqu'à deux parents. Export Excel accepté (séparateur `;`).

```sh
docker compose up -d postgres
docker compose run --rm migrations
docker compose run --rm -v ./config:/config api importer /config/ecole.json /config/familles.csv --essai
docker compose run --rm -v ./config:/config api importer /config/ecole.json /config/familles.csv
```

L'option `--essai` valide les fichiers sans rien écrire ; corriger les
erreurs signalées (elles citent la ligne et la colonne, jamais un nom
d'enfant). Le second import affiche l'**identifiant de l'établissement** :
le recopier dans `BALLAN_ETABLISSEMENT_ID`.

> Les dates des fêtes religieuses (Aïd, Ramadan) changent chaque année et
> doivent être confirmées par l'école dans `ecole.json`.

---

## 4. Démarrer et vérifier

```sh
docker compose up -d --build
docker compose run --rm api verifier
```

`verifier` doit afficher `[ok]` partout sauf, éventuellement, les points
`[!!]` non bloquants. Un point `[KO]` sur les langues signifie qu'une langue
activée n'est pas encore relue par un locuteur natif (voir
`core/i18n/locales/RELECTURE.md`). Deux options :

- retirer la langue de `langues_actives` dans `ecole.json` et réimporter ;
- pour un **pilote encadré**, avec l'accord écrit de l'école,
  `BALLAN_AUTORISER_LANGUES_NON_RELUES=1`.

Contrôler : `https://<domaine>/sante` répond `{"statut":"ok"}`.

---

## 5. Brancher le webhook

Dans l'application Meta, *WhatsApp → Configuration → Webhook* :

- URL de rappel : `https://<domaine>/webhook/whatsapp`
- Jeton de vérification : la valeur de `WHATSAPP_VERIFY_TOKEN`
- S'abonner au champ **messages**.

Envoyer « bonjour » au numéro de l'école depuis un téléphone de parent
présent dans le CSV : le menu doit arriver. Depuis un numéro absent du CSV :
le message de refus, et une demande apparaît sur la page du secrétariat.

---

## 6. Remettre au secrétariat

- Page : `https://<domaine>/secretariat` — utilisateur `secretariat`, mot de
  passe `BALLAN_ADMIN_TOKEN`. À ouvrir uniquement sur les postes de l'école.
- Au quotidien : rappeler les numéros de la rubrique « À rappeler », puis
  cliquer « Traité ».
- **Nouveau numéro, nouvel élève, départ** : corriger le CSV et réimporter
  (étape 3), puis recharger la configuration :
  `curl -X POST -H "Authorization: Bearer $BALLAN_ADMIN_TOKEN" https://<domaine>/admin/configuration/recharger`.
  Un numéro retiré du CSV perd l'accès dès l'import ; un élève absent du CSV
  passe « sorti » (option `--garder-absents` pour l'éviter).

---

## Exploitation

| Besoin | Commande |
|---|---|
| Journaux | `docker compose logs -f api rappels` (JSON, numéros masqués) |
| État des services | `docker compose ps` |
| Mise à jour | `git pull && docker compose up -d --build` (les migrations passent seules) |
| Sauvegarde manuelle | `docker compose exec sauvegarde pg_dump -h postgres -U ballan -d ballan -Fc -f /sauvegardes/manuelle.dump` |
| Restauration | `docker compose stop api rappels entretien` puis `docker compose exec -T postgres pg_restore -U ballan -d ballan --clean --if-exists < sauvegardes/<fichier>.dump` puis `docker compose start api rappels entretien` |

Les sauvegardes quotidiennes restent 14 jours dans `./sauvegardes` **sur le
même serveur** : elles ne protègent pas d'une perte du serveur. Les copier
chaque semaine ailleurs (`rsync`, stockage objet chiffré). Tester une
restauration avant la mise en service.

---

## Limites connues de la version 0.2

- **Langues** : arabe, somali et afar sont des traductions de travail, à faire
  relire avant tout usage réel (l'afar en priorité).
- **Reconnaissance de texte libre** : l'agent comprend les numéros, « menu »,
  « STOP », « langue » et repère les sujets interdits par mots-clés ; il ne
  comprend pas une phrase comme « je veux voir la maîtresse jeudi » (il
  renvoie alors le menu).
- **Annulation par l'école** : le parent n'est pas prévenu automatiquement ;
  le secrétariat l'appelle.
- **Une école par déploiement** : un numéro WhatsApp, une base, un
  `BALLAN_ETABLISSEMENT_ID`.
- **Pas encore** de réunions parents-professeurs collectives ni d'annonces
  (lots 4 et 5), ni de saisie en ligne de la configuration (lot 6).
