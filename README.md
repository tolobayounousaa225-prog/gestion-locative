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

- Portail locataire en lecture seule (consulter son bail, ses paiements).
- Rappels automatiques des impayés (email/SMS).
- Génération automatique de l'échéancier mensuel à partir des baux actifs.
- Mobile money / virement en plus des espèces.
