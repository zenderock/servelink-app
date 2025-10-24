# Monitoring des Projets Inactifs

## Vue d'ensemble

Le système de monitoring des projets inactifs désactive automatiquement les projets du plan gratuit qui n'ont pas reçu de trafic pendant une période donnée, afin d'optimiser les ressources et d'encourager l'utilisation active de la plateforme.

## Fonctionnement

### Règles de Désactivation

1. **Plan Gratuit** :
   - Projets inactifs depuis **5 jours** → Statut `inactive` (désactivation temporaire) + **Email de notification**
   - Projets `inactive` depuis **7 jours supplémentaires** → Statut `permanently_disabled` (désactivation définitive) + **Email de notification**

2. **Plan Payant** :
   - Aucune désactivation automatique

### Statuts des Projets

- `active` : Projet normalement actif
- `inactive` : Projet temporairement désactivé (peut être réactivé)
- `permanently_disabled` : Projet définitivement désactivé (ne peut plus être réactivé)
- `paused` : Projet mis en pause manuellement
- `deleted` : Projet supprimé

## Architecture

### Composants Principaux

1. **ProjectMonitoringService** (`app/services/project_monitoring.py`)
   - `check_inactive_projects()` : Détecte et désactive les projets inactifs
   - `check_permanently_disabled_projects()` : Désactive définitivement les projets
   - `reactivate_project()` : Réactive un projet inactif
   - `record_traffic()` : Enregistre le trafic sur un projet

2. **Middleware TrafficRecorder** (`app/middleware/traffic_recorder.py`)
   - Intercepte les requêtes vers les projets
   - Enregistre le trafic automatiquement
   - Bloque l'accès aux projets désactivés

3. **Tâches ARQ** (`app/workers/tasks/project_monitoring.py`)
   - `check_inactive_projects` : Tâche périodique (quotidienne à 02h00 UTC)
   - `reactivate_project_task` : Tâche de réactivation asynchrone

### Base de Données

#### Nouveaux Champs dans la Table `project`

- `last_traffic_at` : Timestamp de la dernière activité
- `deactivated_at` : Timestamp de la désactivation
- `reactivation_count` : Nombre de réactivations

#### Nouveaux Statuts

- `inactive` : Désactivation temporaire
- `permanently_disabled` : Désactivation définitive

## Utilisation

### Réactivation d'un Projet

1. Accéder à la page du projet
2. Cliquer sur "Réactiver" si le statut est `inactive`
3. La réactivation se fait immédiatement avec un message de confirmation

### Vérification du Statut

Le statut du projet est visible :
- Sur la page du projet (badge de statut)
- Dans la liste des projets de l'équipe
- Via l'API (champ `status`)

## Configuration

### Tâche Cron

La vérification des projets inactifs s'exécute automatiquement tous les jours à 02h00 UTC via la configuration ARQ :

```python
cron_jobs = [
    cron(check_inactive_projects, hour=2, minute=0, run_at_startup=False),  # Tous les jours à 02h00 UTC
    cron(cleanup_inactive_deployments, hour=3, minute=0, run_at_startup=False),  # Nettoyage à 03h00 UTC
]
```

### Variables d'Environnement

Aucune variable d'environnement supplémentaire n'est requise. Le système utilise la configuration existante.

## Scripts Utilitaires

### Initialisation des Projets Existants

```bash
python scripts/init_project_traffic.py
```

Initialise `last_traffic_at` pour tous les projets existants avec leur `updated_at`.

### Test des Notifications Email

```bash
python scripts/test_email_notifications.py
```

Teste l'envoi des notifications email de désactivation.

### Test du Système

```bash
python scripts/test_project_monitoring.py
```

Exécute une suite de tests complète pour vérifier le bon fonctionnement du système.

## Interface Utilisateur

### Templates

- `project/partials/_project_status.html` : Affichage du statut sur la page projet avec bouton de réactivation
- `project/partials/_project_status_badge.html` : Badge de statut dans les listes
- `project/partials/_project_activity_info.html` : Informations d'activité

### Templates Email

- `email/project-disabled.html` : Email de notification pour désactivation temporaire
- `email/project-permanently-disabled.html` : Email de notification pour désactivation permanente

### Messages d'Erreur

- Page d'erreur personnalisée pour les projets désactivés
- Messages flash pour les actions de réactivation
- Indicateurs visuels de statut

## Monitoring et Logs

### Logs

Toutes les actions sont loggées avec le niveau approprié :
- `INFO` : Désactivation/réactivation réussie
- `WARNING` : Tentative de réactivation impossible
- `ERROR` : Erreurs lors des opérations

### Métriques

Les statistiques d'équipe incluent maintenant :
- Nombre de projets actifs
- Nombre de projets inactifs
- Nombre de projets définitivement désactivés

## Tests

### Tests d'Intégration

Le fichier `app/tests/test_project_monitoring.py` contient des tests complets pour :
- Désactivation après 5 jours
- Désactivation permanente après 7 jours supplémentaires
- Réactivation réussie
- Réactivation impossible
- Enregistrement du trafic
- Projets du plan payant non affectés
- Envoi de notifications email

### Exécution des Tests

```bash
pytest app/tests/test_project_monitoring.py -v
```

## Migration

### Migration de la Base de Données

La migration `20250122_add_project_inactivity_tracking.py` :
1. Ajoute les nouveaux statuts à l'enum `project_status`
2. Ajoute les nouveaux champs à la table `project`
3. Crée un index sur `last_traffic_at`
4. Initialise `last_traffic_at` pour les projets existants

### Déploiement

1. Appliquer la migration : `alembic upgrade head`
2. Initialiser les projets existants : `python scripts/init_project_traffic.py`
3. Redémarrer les workers ARQ
4. Vérifier le fonctionnement : `python scripts/test_project_monitoring.py`

## Sécurité

- Seuls les propriétaires et administrateurs peuvent réactiver les projets
- Les projets désactivés ne sont plus accessibles via leurs domaines
- Le middleware bloque automatiquement l'accès aux projets inactifs
- Les configurations Traefik sont supprimées pour les projets désactivés

## Limitations

- Les projets du plan gratuit sont les seuls affectés
- La réactivation n'est possible que pour les projets `inactive`
- Les projets `permanently_disabled` ne peuvent plus être réactivés
- Le système ne distingue pas le type de trafic (API vs web)
