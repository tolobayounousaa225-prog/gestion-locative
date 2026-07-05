# Gestion Locative

Application de gestion locative (maisons, locataires, baux, loyers, maintenance) pour un gérant unique.

## Structure

```
backend/
  main.py            API FastAPI (auth JWT, CRUD, dashboard, quittance PDF)
  requirements.txt
frontend/
  index.html         Interface (HTML/CSS/JS, sans framework)
render.yaml           Config de déploiement Render (web service + base Postgres)
```

## Lancer en local

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --app-dir .
```

Ouvrir http://localhost:8000 — le backend sert directement le frontend.

Identifiants par défaut (créés automatiquement au premier démarrage) :
- Email : `admin@gestion-locative.local`
- Mot de passe : `changeMoi123`

Pour changer ces identifiants, définir les variables d'environnement `ADMIN_EMAIL` et `ADMIN_PASSWORD` avant de lancer le serveur.

## Fonctionnalités

- Gestion des maisons, locataires, baux, paiements (encaissements en espèces/mobile money/virement) et tickets de maintenance.
- Quittance PDF professionnelle avec QR code de vérification après chaque encaissement.
- Chaque utilisateur peut modifier son nom, son email ou son mot de passe depuis la section Utilisateurs (« Mon profil »).
- Export PDF de la liste des locataires + impression directe.
- **Portail locataire en lecture seule** : générez un lien personnel par locataire (bouton « Portail » dans la section Locataires) donnant accès à son bail et son historique de paiements, sans compte ni mot de passe.
- **Compte de connexion locataire** : bouton « Créer un accès » sur la fiche locataire — le gérant définit un email et un mot de passe, que le locataire peut ensuite utiliser pour se connecter (comme un gérant/propriétaire) et voir dans « Mon espace » : son bail/contrat, l'historique de ses paiements, ses reçus (quittances PDF), et envoyer un message au gérant (onglet Observations). Le locataire ne voit que ses propres données.
- **Rappels d'impayés** (section « Rappels ») : liste des baux impayés du mois avec lien WhatsApp pré-rempli pour un rappel manuel en un clic, et envoi automatique par email si le locataire a une adresse email et que le SMTP est configuré (voir ci-dessous). Un job quotidien envoie aussi ces rappels automatiquement.
- **Échéancier mensuel automatique** : bouton « Générer l'échéancier du mois » dans Paiements (crée un paiement « en attente » par bail actif), également généré automatiquement le 1er de chaque mois.
- **Bilan mensuel** exportable en PDF et en Excel, en plus de l'affichage à l'écran.
- **Journal de connexion** (section « Journal de connexion », gérant uniquement) : historique des tentatives de connexion (succès/échec, IP, navigateur).

## Envoi d'emails (SMTP)

Par défaut, l'email de réinitialisation de mot de passe est simplement affiché à l'écran (aucun envoi réel), pratique pour le développement. Pour activer l'envoi réel d'emails (réinitialisation de mot de passe + rappels d'impayés), définir ces variables d'environnement :

- `SMTP_HOST`, `SMTP_PORT` (défaut 587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (défaut = `SMTP_USER`), `SMTP_USE_TLS` (défaut `true`)

Tant que `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD` ne sont pas tous renseignés, l'application reste utilisable normalement (liens affichés à l'écran, rappels visibles uniquement via WhatsApp).

## Créer le dépôt GitHub

```bash
cd chemin/vers/le/projet
git init
git add .
git commit -m "Initial commit — scaffold gestion locative"
git branch -M main
git remote add origin https://github.com/<ton-compte>/gestion-locative.git
git push -u origin main
```

## Déployer sur Render

1. Sur render.com, créer un nouveau Blueprint et pointer vers ce dépôt GitHub — Render lira render.yaml automatiquement (web service + base PostgreSQL).
2. Renseigner la variable d'environnement ADMIN_PASSWORD dans le dashboard Render (elle n'est pas versionnée par sécurité).
3. Une fois déployé, Render fournit une URL publique type https://gestion-locative.onrender.com.

## Prochaines étapes possibles

- Envoi de vrais SMS (intégration d'un fournisseur type Twilio/Orange API) en plus du lien WhatsApp.
- Notifications push/email au gérant en cas de nouvel impayé.
- Signature électronique des baux.
