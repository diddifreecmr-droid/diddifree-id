# Brief complémentaire — choix du canal OTP

## Règle générale

`OTP_PROVIDER` définit le canal par défaut côté backend. Le frontend choisit un
canal fonctionnel (`sms`, `email`, `telegram` ou `whatsapp`) ; le backend choisit
ensuite le fournisseur configuré pour ce canal.

En staging WhatsApp :

```text
OTP_PROVIDER=whatsapp
```

Le frontend peut toutefois choisir le canal pour chaque demande avec le champ
`channel`. Les valeurs disponibles sont `sms`, `whatsapp`, `email` et `telegram`.

## Demander un OTP par SMS

```json
POST /identity/v1/auth/otp/request

{
  "phone": "+2250700000000",
  "channel": "sms"
}
```

Le canal SMS est neutre vis-à-vis du fournisseur. Pour Yellika en staging,
Portainer doit contenir `OTP_PROVIDER=sms`, `OTP_SMS_PROVIDER=yellika`,
`YELLIKA_SMS_TOKEN` et `YELLIKA_SMS_SENDER_ID`. Le secret n'est jamais placé
dans Git. Le format de message utilise le numéro international sans `+`.

## Demander un OTP WhatsApp

```json
POST /identity/v1/auth/otp/request

{
  "phone": "+23780013501",
  "channel": "whatsapp"
}
```

WhatsApp nécessite un numéro de téléphone. Le backend transmet le numéro au
format international sans le signe `+` à Evolution API.

## Demander un OTP par email

```json
POST /identity/v1/auth/otp/request

{
  "email": "user@example.com",
  "channel": "email"
}
```

Pour un login par email, le frontend envoie donc uniquement l'adresse email et
`channel: "email"`. L'adresse doit appartenir au compte DiddiFreeID.

Un compte qui possède téléphone et email peut aussi demander l'email avec son
numéro :

```json
{
  "phone": "+23780013501",
  "channel": "email"
}
```

Dans ce cas, Auth utilise l'adresse email enregistrée sur le profil.

## Vérifier le code

La vérification utilise le même identifiant que la demande :

```json
POST /identity/v1/auth/otp/verify

{
  "email": "user@example.com",
  "code": "482913"
}
```

ou :

```json
{
  "phone": "+23780013501",
  "code": "482913"
}
```

Chaque requête OTP doit fournir exactement un identifiant : `phone` ou
`email`, jamais les deux ensemble.

## Ajouter un contact à un compte existant

Un email ou un téléphone ne doit pas être écrit directement dans le profil sans
preuve de possession. L'utilisateur authentifié demande un challenge :

```json
POST /identity/v1/users/me/contact/request

{
  "phone": "+2250700000000",
  "channel": "sms"
}
```

Puis il vérifie le code reçu :

```json
POST /identity/v1/users/me/contact/verify

{
  "phone": "+2250700000000",
  "code": "482913"
}
```

Le même workflow s'applique à un nouvel email avec `channel: "email"`. Le
contact est attaché au même `user_id`, et un contact déjà utilisé par un autre
compte est refusé. L'email est aussi protégé par un index PostgreSQL unique
insensible à la casse.

## Logs staging

Avec `OTP_LOG_PLAINTEXT=true`, le code reste visible dans les logs quel que
soit le canal. Mettre `OTP_LOG_PLAINTEXT=false` avant la production.

## Portainer

Les variables Evolution API sont configurées uniquement dans Portainer :

```text
OTP_PROVIDER=whatsapp
EVOLUTION_API_URL=<url Evolution API>
EVOLUTION_API_KEY=<clé Evolution API>
EVOLUTION_INSTANCE=<nom de l'instance>
```

Pour Yellika SMS :

```text
OTP_PROVIDER=sms
OTP_SMS_PROVIDER=yellika
YELLIKA_SMS_BASE_URL=https://panel.yellikasms.com
YELLIKA_SMS_TOKEN=<secret Portainer>
YELLIKA_SMS_SENDER_ID=<sender_id autorisé>
YELLIKA_SMS_TIMEOUT_SECONDS=20
```

Pour Senndo SMS :

```text
OTP_PROVIDER=sms
OTP_SMS_PROVIDER=senndo
SENNDO_SMS_BASE_URL=https://api.senndo.com
SENNDO_SMS_API_KEY=<secret Portainer>
SENNDO_SMS_TIMEOUT_SECONDS=30
```

Senndo exige une clé d'idempotence par envoi. DiddiFreeID la dérive sans
exposer le code OTP, afin qu'une nouvelle tentative réseau ne crée pas un
second message pour le même code.

Le compose Portainer n'est pas modifié par ce brief.
