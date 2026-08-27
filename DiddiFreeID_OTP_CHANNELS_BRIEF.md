# Brief complémentaire — choix du canal OTP

## Règle générale

`OTP_PROVIDER` définit le canal par défaut côté backend. En staging WhatsApp :

```text
OTP_PROVIDER=whatsapp
```

Le frontend peut toutefois choisir le canal pour chaque demande avec le champ
`channel`. Les valeurs disponibles sont `whatsapp`, `email` et `telegram`.

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

Le compose Portainer n'est pas modifié par ce brief.
