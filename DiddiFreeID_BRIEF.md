# Brief DiddiFreeID

## Rôle du service

DiddiFreeID est le fournisseur central d'identité de DiddiFree. Il gère :

- l'inscription et la connexion par OTP ;
- les tokens JWT RS256 et le JWKS ;
- le profil partagé : numéro vérifié, nom, langue `fr|en` et `photo_url` ;
- les statuts globaux `pending_verification`, `active` et `suspended` ;
- les rôles globaux de plateforme : `user` et `admin` ;
- les événements d'identité et la lecture de profil service-to-service.

Chaque module vérifie les JWT localement avec le JWKS. Il ne doit pas appeler
Auth à chaque requête simplement pour vérifier un token.

## Rôles métier

Les rôles métier ne sont pas centralisés dans Auth :

- DiddiGo possède `driver_profiles` et décide si un utilisateur peut conduire ;
- DiddiPay possède ses profils et permissions de paiement ;
- DiddiFund possède ses rôles d'investissement et de campagne ;
- les autres modules gardent leurs propres rôles métier.

Les anciennes valeurs `driver` et `merchant` peuvent encore être lues pendant
la migration des anciennes lignes, mais Auth refuse désormais de les attribuer
avec `409 ROLE_OWNED_BY_MODULE`. Le rôle métier ne doit pas être ajouté au JWT
central. Le module propriétaire peut publier un événement métier ou fournir un
endpoint interne si un autre module doit connaître cette qualification.

## Profil et numéro

`PATCH /identity/v1/users/me` permet de modifier le nom, la langue et le lien
de photo. Une photo peut être supprimée avec `photo_url: null`.

Le numéro est une donnée d'identité vérifiée. Il ne doit pas être changé par le
PATCH général : il faudra une procédure OTP dédiée sur le nouveau numéro.

## OTP Telegram staging

Le transport peut être activé dans Portainer avec :

```text
OTP_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=<secret fourni par Portainer>
```

Le token n'est jamais versionné. L'utilisateur ouvre le bot, partage son
propre contact, puis Auth lie `telegram_user_id` et `telegram_chat_id` à son
compte. Les OTP suivants sont envoyés dans ce chat privé. Le worker utilise le
long polling Telegram et supprime le webhook au démarrage.

## Points et Loyalty

Auth ne stocke pas de solde de points. Un service Loyalty central possédera le
ledger, les règles, les annulations et l'historique. Les modules source lui
notifieront les opérations confirmées : trajets, paiements, dépôts et
parrainages. Chaque écriture devra être idempotente.

Le contrat d'intégration est dans
`DiddiFreeID_Loyalty_Integration.md`. Le projet Loyalty n'existe pas encore
dans ce dépôt.

## Déploiement Portainer

`docker-compose.portainer.yml` ne charge pas de fichier `.env`. Les variables
sont fournies directement dans Portainer. La base et Redis restent internes à
la stack, l'application attend la base, exécute `alembic upgrade head`, puis
démarre l'API. Les clés JWT sont générées dans le volume Docker persistant.

## État actuel

Les migrations Telegram et profil sont présentes. Les contrôles de compilation
et de format de diff passent. Les tests d'intégration nécessitent les
dépendances Python, PostgreSQL, Redis et Docker disponibles dans
l'environnement d'exécution.
