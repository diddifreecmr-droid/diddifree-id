# Intégration DiddiFreeID avec Loyalty

## Responsabilités

DiddiFreeID est propriétaire de l'identité et du profil global : `user_id`,
numéro vérifié, nom, langue et lien de photo. Il ne stocke pas le solde de
points et n'accepte pas de crédit de points depuis un client.

Le module **Loyalty** est propriétaire du programme de fidélité : ledger des
écritures, solde calculé, règles de récompense, annulations et historique.

## Sources de points

Les quatre sources prévues sont :

- `ride` : trajet terminé ou action de trajet validée ;
- `payment` : paiement confirmé ;
- `deposit` : dépôt confirmé ;
- `referral` : parrainage validé selon les règles métier.

Le module source appelle Loyalty après la confirmation de son opération. Il ne
modifie jamais la base Auth et Auth ne modifie jamais le ledger Loyalty.

## Écriture idempotente

Chaque crédit ou débit doit porter une clé `idempotency_key` stable, construite
à partir du module source et de la référence métier, par exemple
`ride:{ride_id}:completed`. Loyalty doit rendre la même écriture lorsqu'une
requête est rejouée et refuser une même clé avec un contenu différent.

Le contrat interne minimal d'une écriture est :

```json
{
  "user_id": "uuid",
  "source": "ride|payment|deposit|referral",
  "action": "completed|confirmed|validated|cancelled",
  "points": 10,
  "idempotency_key": "ride:uuid:completed",
  "reference_id": "uuid",
  "metadata": {}
}
```

`points` est signé : une annulation ou correction peut donc débiter le ledger.
Le client ne peut pas appeler cette écriture ; elle est réservée aux appels
service-à-service authentifiés.

## Lecture

L'application consommera Loyalty pour afficher le solde et l'historique. Le
profil Auth ne contiendra pas de champ `points`, afin d'éviter deux sources de
vérité.

## Événements Auth utiles

Loyalty peut consommer `user.registered` pour préparer son compte utilisateur.
Les événements `user.updated` servent uniquement à mettre à jour une copie de
profil utile à l'affichage ; ils ne créditent aucun point.

Le changement de numéro sera une procédure Auth séparée avec OTP sur le nouveau
numéro. Il ne doit pas être réalisé par le `PATCH /users/me` général.
