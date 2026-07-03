# Cahier des charges — Application de Gestion Locative

## 1. Contexte et objectif

Application permettant à un gérant (toi) de suivre les maisons d'un propriétaire, les locataires installés dans chaque maison, l'encaissement des loyers chaque mois, et les demandes de maintenance/réparations.

## 2. Rôles

- Gérant / Admin — accès total : ajoute des maisons, des locataires, encaisse les loyers, suit la maintenance.
- Locataire (phase 2, optionnel) — portail simple pour consulter son bail, son historique de paiement, signaler un problème.

Pour la V1, un seul rôle actif : Gérant. Le compte locataire est prévu dans le modèle de données pour ne pas bloquer une extension future.

## 3. Modules (compartiments)

### 3.1 Biens & unités (socle indispensable)
Fiche par maison : adresse, propriétaire, nombre de pièces, loyer mensuel de référence, statut (occupée / libre / en travaux), photos.

### 3.2 Locataires & baux
- Fiche locataire : nom, téléphone, pièce d'identité, contact d'urgence.
- Bail : maison liée, locataire lié, date de début, durée, montant du loyer, caution versée, statut (actif / résilié).
- État des lieux (entrée/sortie) en pièce jointe.

### 3.3 Loyers & paiements
- Échéancier automatique généré à partir du bail (1 échéance / mois).
- Enregistrement d'un encaissement (montant, date, mode : espèces/mobile money/virement).
- Statut par échéance : payé / partiel / en retard.
- Génération de quittance (PDF) à chaque paiement.
- Vue "impayés du mois" pour relance.

### 3.4 Maintenance & tickets
- Création d'un ticket lié à une maison (et au locataire si signalé par lui).
- Statut : ouvert / en cours / résolu.
- Coût de la réparation (pour suivi budgétaire par maison).
- Historique par maison.

### 3.5 Tableau de bord
- Total loyers attendus / encaissés du mois.
- Liste des impayés.
- Tickets de maintenance ouverts.
- Taux d'occupation (maisons occupées / total).

## 4. Modèle de données (simplifié)

```
users            (id, nom, email, mot_de_passe_hash, role)
maisons          (id, adresse, proprietaire, nb_pieces, loyer_reference, statut)
locataires       (id, nom, telephone, piece_identite, contact_urgence)
baux             (id, maison_id, locataire_id, date_debut, date_fin, loyer_mensuel, caution, statut)
paiements        (id, bail_id, mois_concerne, montant, date_paiement, mode, statut)
tickets          (id, maison_id, locataire_id, description, statut, cout, date_creation, date_resolution)
```

Relations : une maison a plusieurs baux dans le temps (mais un seul actif) ; un bail a plusieurs paiements (un par mois) ; une maison a plusieurs tickets.

## 5. Écrans principaux

1. Connexion (gérant)
2. Tableau de bord — synthèse du mois
3. Maisons — liste + fiche détail (baux, historique, tickets liés)
4. Locataires — liste + fiche détail
5. Baux — création/consultation, lié à une maison + un locataire
6. Paiements — échéancier du mois, encaissement en un clic, génération quittance
7. Maintenance — liste des tickets, création, changement de statut

## 6. Architecture technique (identique à CODISS)

- Backend : Python / FastAPI (main.py), base SQLite en développement (migrable vers PostgreSQL sur Render).
- Frontend : index.html monofichier (HTML + CSS + JS), sans framework lourd, à l'image de CODISS.
- Versioning : dépôt GitHub à créer.
- Déploiement : Render (web service Python + éventuellement base Postgres managée).

## 7. Roadmap

| Phase | Contenu |
|---|---|
| V1 | Maisons, Locataires & baux, Paiements, Tableau de bord |
| V1.1 | Maintenance & tickets |
| V2 | Portail locataire (lecture seule), génération quittance PDF automatique, rappels SMS/mobile money |

## 8. Points validés

- Mode de paiement en priorité : espèces.
- Un seul propriétaire pour l'instant.
- Quittance PDF téléchargeable suffit pour la V1.
