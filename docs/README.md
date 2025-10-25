# Documentation Servelink

Cette documentation couvre l'architecture, les fonctionnalités et les intégrations de Servelink.

## 📚 Index des documents

### 🏗️ Architecture

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Architecture générale de l'application
- **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Guide de contribution

### 💰 Système de pricing et paiements

- **[PRICING_COMPLETE_IMPLEMENTATION.md](./PRICING_COMPLETE_IMPLEMENTATION.md)** - **📊 Récapitulatif complet**
  - Vue d'ensemble de toutes les fonctionnalités
  - Haute priorité (100% ✅)
  - Moyenne priorité (100% ✅)
  - Statistiques et métriques
  - Checklist de déploiement

- **[PAYMENT_INTEGRATION.md](./PAYMENT_INTEGRATION.md)** - Documentation complète de l'intégration des paiements
  - Endpoints Servelink
  - Flux de paiement complet
  - Exemples de requêtes/réponses
  - Guide d'intégration

- **[PAYMENT_BACKEND_SPEC.md](./PAYMENT_BACKEND_SPEC.md)** - **Spécifications pour le backend de paiement externe**
  - Endpoints requis (POST /initiate, GET /status, POST /cancel)
  - Format des webhooks
  - Codes d'erreur
  - Exemples d'implémentation
  - Checklist de mise en production

- **[IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)** - Résumé implémentation haute priorité
  - Tracking trafic et stockage
  - Système de paiement
  - Services créés
  - Migrations DB
  - Configuration requise

- **[MEDIUM_PRIORITY_FEATURES.md](./MEDIUM_PRIORITY_FEATURES.md)** - Fonctionnalités moyenne priorité
  - Ressources additionnelles (RAM, CPU, Trafic, Stockage)
  - Priority Support (système de tickets)
  - Dashboard d'utilisation avancé
  - Endpoints API complets

### 📊 Monitoring et tracking

- **[PROJECT_MONITORING.md](./PROJECT_MONITORING.md)** - Système de monitoring des projets inactifs
  - Règles de désactivation
  - Architecture du middleware
  - Cronjobs configurés
  - Réactivation de projets

### 🔐 Validation

- **[START_COMMAND_VALIDATION.md](./START_COMMAND_VALIDATION.md)** - Validation des commandes de démarrage
  - Serveurs supportés
  - Règles de validation
  - Exemples de commandes valides/invalides

## 🚀 Quick Start - Intégration du système de paiement

### 1. Configuration

Ajoutez ces variables au fichier `.env` :

```bash
PAYMENT_BACKEND_URL=http://localhost:8001
PAYMENT_API_KEY=your_secret_api_key_here
BASE_URL=https://your-domain.com
```

### 2. Migration de base de données

```bash
cd app
alembic upgrade head
```

### 3. Implémentez le backend de paiement

Consultez **[PAYMENT_BACKEND_SPEC.md](./PAYMENT_BACKEND_SPEC.md)** pour les spécifications exactes.

**Endpoints minimum requis :**
- `POST /api/v1/payments/initiate`
- `GET /api/v1/payments/{external_payment_id}/status`
- `POST /api/v1/payments/{external_payment_id}/cancel`

### 4. Testez l'intégration

```bash
# Test d'initialisation de paiement
curl -X POST http://localhost:8000/api/payments/my-team/initiate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "amount": 3.0,
    "payment_method": "mobile_money",
    "plan_upgrade": true,
    "new_plan": "pay_as_you_go"
  }'
```

## 📖 Guides détaillés

### Pour les développeurs

1. **Ajouter un nouveau plan de pricing**
   - Modifier `/app/models.py` (SubscriptionPlan)
   - Créer une migration Alembic
   - Mettre à jour `/app/services/pricing.py`
   - Mettre à jour les templates

2. **Ajouter une nouvelle méthode de paiement**
   - Modifier `/app/models.py` (enum payment_method)
   - Mettre à jour `/app/services/payment.py`
   - Créer la migration
   - Ajouter dans l'interface utilisateur

3. **Modifier les limites de tracking**
   - Modifier `/app/services/usage_tracking.py`
   - Ajuster les cronjobs dans `/app/workers/arq.py`
   - Mettre à jour les alertes

### Pour les intégrateurs de backend de paiement

Suivez ce workflow :

1. **Lisez la spécification complète** : [PAYMENT_BACKEND_SPEC.md](./PAYMENT_BACKEND_SPEC.md)
2. **Implémentez les 3 endpoints requis**
3. **Configurez le webhook callback**
4. **Testez en sandbox** avec les montants de test
5. **Validez avec la checklist** dans la spec
6. **Passez en production**

### Pour les ops

1. **Monitoring des paiements**
   - Vérifier les logs : `docker logs servelink-app | grep payment`
   - Métriques dans Grafana
   - Alertes sur taux d'échec > 5%

2. **Monitoring de l'utilisation**
   - Cronjob de tracking : tous les jours à 4h00 et 6h00 UTC
   - Logs dans `/app/workers/tasks/usage_monitoring.py`
   - Alertes automatiques à 80% et 95%

3. **Troubleshooting**
   - Paiement bloqué → Vérifier le statut via `/api/payments/{id}/status`
   - Usage non mis à jour → Vérifier les cronjobs ARQ
   - Callback échoué → Vérifier les logs du backend de paiement

## 🔄 Flux de données

### Tracking du trafic

```
Requête HTTP → TrafficRecorderMiddleware
    ↓
Enregistrement dans project.last_traffic_at
    ↓
Calcul des octets transférés (Content-Length)
    ↓
UsageTrackingService.record_traffic()
    ↓
Mise à jour de project_usage.traffic_bytes
```

### Tracking du stockage

```
Cronjob quotidien (4h00 UTC)
    ↓
update_project_storage()
    ↓
Calcul via Docker API (volumes + images)
    ↓
UsageTrackingService.update_storage()
    ↓
Mise à jour de project_usage.storage_bytes
```

### Flux de paiement

```
Frontend → POST /api/payments/{team_slug}/initiate
    ↓
PaymentService.initiate_payment()
    ↓
POST {PAYMENT_BACKEND_URL}/api/v1/payments/initiate
    ↓
Réception external_payment_id + payment_url
    ↓
Redirection utilisateur
    ↓
Paiement effectué
    ↓
Webhook POST /api/payments/callback
    ↓
Activation du plan Pro automatique
```

## 📊 Modèles de données

### ProjectUsage

```sql
CREATE TABLE project_usage (
    id VARCHAR(32) PRIMARY KEY,
    project_id VARCHAR(32) NOT NULL,
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    traffic_bytes BIGINT DEFAULT 0,
    storage_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE(project_id, year, month)
);
```

### Payment

```sql
CREATE TABLE payment (
    id VARCHAR(32) PRIMARY KEY,
    team_id VARCHAR(32) NOT NULL,
    external_payment_id VARCHAR(255) UNIQUE,
    amount FLOAT NOT NULL,
    currency VARCHAR(3) DEFAULT 'EUR',
    payment_method payment_method_enum NOT NULL,
    status payment_status_enum DEFAULT 'pending',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);
```

## 🧪 Tests

### Tests unitaires

```bash
# Tests du service de tracking
pytest app/tests/test_usage_tracking.py

# Tests du service de paiement
pytest app/tests/test_payment_service.py

# Tests d'intégration
pytest app/tests/test_pricing_integration.py
```

### Tests manuels

```bash
# Tester l'enregistrement du trafic
curl -v http://your-project.servelink.com

# Vérifier l'utilisation
curl http://localhost:8000/api/usage/{team_id}/summary

# Tester l'initialisation de paiement
curl -X POST http://localhost:8000/api/payments/my-team/initiate \
  -H "Content-Type: application/json" \
  -d '{"amount": 3.0, "payment_method": "mobile_money"}'
```

## 🚨 Alertes et notifications

### Alertes d'utilisation

- **80% utilisé** : Email d'avertissement
- **95% utilisé** : Email critique + badge dans l'interface
- **100% dépassé** : Blocage temporaire (à implémenter)

### Alertes de paiement

- Paiement échoué → Email à l'utilisateur
- Paiement complété → Email de confirmation
- Paiement en attente > 24h → Email de rappel

## 📝 TODO / Roadmap

### Court terme

- [ ] Implémenter le blocage à 100% d'utilisation
- [ ] Ajouter les emails de notification d'utilisation
- [ ] Créer le dashboard d'analytics
- [ ] Tests end-to-end du flux de paiement

### Moyen terme

- [ ] Support de ressources additionnelles payantes
- [ ] Webhooks personnalisés pour les événements
- [ ] API publique pour les statistiques
- [ ] Export CSV des données d'utilisation

### Long terme

- [ ] Priority support avec système de tickets
- [ ] Advanced analytics avec graphiques
- [ ] Multi-currency support
- [ ] Facturation automatique mensuelle

## 📞 Support

### Pour les questions techniques

- Email : dev@servelink.com
- GitHub Issues : https://github.com/servelink/issues
- Discord : https://discord.gg/servelink

### Pour les questions de paiement

- Email : payments@servelink.com
- Documentation : Cette documentation
- Statut de l'API : https://status.servelink.com

## 🔗 Liens utiles

- [Site web](https://servelink.com)
- [Pricing](https://servelink.com/pricing)
- [Blog](https://servelink.com/blog)
- [GitHub](https://github.com/servelink)
- [Status Page](https://status.servelink.com)
