# Fonctionnalités de moyenne priorité implémentées

Ce document décrit les fonctionnalités de moyenne priorité qui ont été implémentées pour Servelink.

## 📦 Vue d'ensemble

### Fonctionnalités implémentées

1. ✅ **Ressources additionnelles payantes** - RAM, CPU, Trafic, Stockage supplémentaires
2. ✅ **Priority Support** - Système de tickets avec priorité pour le plan Pro
3. 🔄 **Dashboard d'utilisation avancé** - Interface UI à compléter

---

## 1. Ressources additionnelles (Add-ons)

### Description

Les équipes sur le plan Pro peuvent acheter des ressources supplémentaires au-delà des limites de base du plan.

### Tarification (selon pricing-specs.json)

| Ressource | Unité | Prix mensuel |
|-----------|-------|--------------|
| **RAM additionnelle** | +500 MB | 1,00 € |
| **CPU additionnel** | +1 CPU | 2,00 € |
| **Trafic additionnel** | +10 GB | 1,00 € |
| **Stockage additionnel** | +10 GB | 1,00 € |

### Modèles de données

#### AdditionalResource

```python
{
    "id": "res_123",
    "team_id": "team_abc",
    "resource_type": "ram",  # ram, cpu, traffic, storage
    "quantity": 2,  # Nombre d'unités
    "unit_price": 1.0,
    "currency": "EUR",
    "payment_id": "pm_xyz",
    "status": "active",  # active, expired, cancelled
    "expires_at": "2025-02-25T10:00:00Z",  # 30 jours après achat
    "created_at": "2025-01-25T10:00:00Z"
}
```

### Service: AdditionalResourceService

**Fichier:** `/app/services/additional_resources.py`

**Méthodes principales:**

```python
# Acheter une ressource
resource = await AdditionalResourceService.purchase_resource(
    team_id="team_123",
    resource_type="ram",
    quantity=2,
    payment_id="pm_xyz",
    db=db
)

# Récupérer les ressources d'une équipe
resources = await AdditionalResourceService.get_team_resources(
    team_id="team_123",
    db=db,
    active_only=True
)

# Calculer le total des ressources
totals = await AdditionalResourceService.get_total_additional_resources(
    team_id="team_123",
    db=db
)
# Retourne: {
#     "ram_mb": 1000,
#     "cpu_cores": 2.0,
#     "traffic_gb": 20,
#     "storage_gb": 10
# }

# Obtenir les limites totales (plan + ressources additionnelles)
limits = await AdditionalResourceService.get_team_limits_with_additional(
    team=team,
    db=db
)

# Annuler une ressource
await AdditionalResourceService.cancel_resource(
    resource_id="res_123",
    db=db
)

# Expirer les ressources (cronjob)
count = await AdditionalResourceService.expire_resources(db)
```

### Endpoints API

**Fichier:** `/app/routers/resources.py`

#### 1. Lister les ressources disponibles

```
GET /api/resources/{team_slug}/available
```

**Réponse:**
```json
{
  "resources": [
    {
      "type": "ram",
      "name": "RAM additionnelle",
      "unit": "500 MB",
      "price": 1.0,
      "currency": "EUR",
      "description": "Ajoutez 500 MB de RAM à votre plan",
      "icon": "memory"
    }
  ]
}
```

#### 2. Acheter une ressource

```
POST /api/resources/{team_slug}/purchase
```

**Corps:**
```json
{
  "resource_type": "ram",
  "quantity": 2
}
```

**Réponse:**
```json
{
  "payment_id": "pm_abc123",
  "resource_id": "res_xyz789",
  "amount": 2.0,
  "payment_url": "https://pay.example.com/xyz789"
}
```

#### 3. Lister les ressources de l'équipe

```
GET /api/resources/{team_slug}/list
```

**Réponse:**
```json
{
  "resources": [
    {
      "id": "res_123",
      "resource_type": "ram",
      "quantity": 2,
      "unit_price": 1.0,
      "status": "active",
      "expires_at": "2025-02-25T10:00:00Z"
    }
  ],
  "totals": {
    "ram_mb": 1000,
    "cpu_cores": 2.0,
    "traffic_gb": 20,
    "storage_gb": 10
  }
}
```

#### 4. Annuler une ressource

```
DELETE /api/resources/{team_slug}/cancel/{resource_id}
```

#### 5. Obtenir les limites totales

```
GET /api/resources/{team_slug}/limits
```

**Réponse:**
```json
{
  "cpu_cores": 6.0,
  "memory_mb": 6644,
  "traffic_gb": 30,
  "storage_mb": 20480,
  "plan_limits": {
    "cpu_cores": 4.0,
    "memory_mb": 6144,
    "traffic_gb": 10,
    "storage_mb": 10240
  },
  "additional_resources": {
    "ram_mb": 500,
    "cpu_cores": 2.0,
    "traffic_gb": 20,
    "storage_gb": 10
  }
}
```

### Cronjob

**Tâche:** `expire_additional_resources`  
**Planification:** Tous les jours à 5h00 UTC  
**Fonction:** Expire automatiquement les ressources dont la date d'expiration est dépassée

---

## 2. Priority Support

### Description

Système de tickets de support avec priorité automatique pour les équipes sur le plan Pro.

### Modèles de données

#### SupportTicket

```python
{
    "id": "ticket_123",
    "team_id": "team_abc",
    "user_id": 42,
    "subject": "Problème de déploiement",
    "description": "Mon application ne démarre pas...",
    "priority": "high",  # low, normal, high, urgent
    "status": "in_progress",  # open, in_progress, waiting, resolved, closed
    "category": "technical",  # technical, billing, feature_request, bug_report, other
    "assigned_to": "support@servelink.com",
    "created_at": "2025-01-25T10:00:00Z",
    "resolved_at": null,
    "closed_at": null
}
```

#### SupportMessage

```python
{
    "id": "msg_123",
    "ticket_id": "ticket_123",
    "user_id": 42,
    "author_type": "user",  # user, support, system
    "message": "Bonjour, j'ai besoin d'aide...",
    "is_internal": false,
    "created_at": "2025-01-25T10:00:00Z"
}
```

### Service: SupportService

**Fichier:** `/app/services/support.py`

**Méthodes principales:**

```python
# Créer un ticket
ticket = await SupportService.create_ticket(
    team_id="team_123",
    user_id=42,
    subject="Problème",
    description="Description...",
    db=db,
    category="technical",
    priority="normal"  # Sera automatiquement "high" pour le plan Pro
)

# Ajouter un message
message = await SupportService.add_message(
    ticket_id="ticket_123",
    user_id=42,
    message="Merci pour votre aide",
    db=db,
    author_type="user"
)

# Récupérer un ticket avec messages
ticket = await SupportService.get_ticket(
    ticket_id="ticket_123",
    db=db,
    load_messages=True
)

# Lister les tickets d'une équipe
tickets = await SupportService.get_team_tickets(
    team_id="team_123",
    db=db,
    status_filter="open",
    limit=50
)

# Mettre à jour le statut
ticket = await SupportService.update_ticket_status(
    ticket_id="ticket_123",
    status="resolved",
    db=db,
    assigned_to="support@servelink.com"
)

# Récupérer les tickets prioritaires
tickets = await SupportService.get_priority_tickets(
    db=db,
    limit=100
)

# Rechercher des tickets
tickets = await SupportService.search_tickets(
    query_text="déploiement",
    team_id="team_123",
    db=db
)

# Statistiques
stats = await SupportService.get_ticket_stats(
    team_id="team_123",
    db=db
)
```

### Endpoints API

**Fichier:** `/app/routers/support.py`

#### 1. Créer un ticket

```
POST /api/support/{team_slug}/tickets
```

**Corps:**
```json
{
  "subject": "Problème de déploiement",
  "description": "Mon application ne démarre pas...",
  "category": "technical",
  "priority": "high"
}
```

**Réponse:**
```json
{
  "ticket_id": "ticket_123",
  "status": "open",
  "priority": "high",
  "category": "technical",
  "created_at": "2025-01-25T10:00:00Z"
}
```

#### 2. Lister les tickets

```
GET /api/support/{team_slug}/tickets?status=open
```

**Réponse:**
```json
{
  "tickets": [
    {
      "id": "ticket_123",
      "subject": "Problème",
      "status": "in_progress",
      "priority": "high",
      "category": "technical",
      "created_at": "2025-01-25T10:00:00Z"
    }
  ]
}
```

#### 3. Voir un ticket

```
GET /api/support/{team_slug}/tickets/{ticket_id}
```

**Réponse:**
```json
{
  "id": "ticket_123",
  "subject": "Problème",
  "description": "Description...",
  "status": "in_progress",
  "priority": "high",
  "messages": [
    {
      "id": "msg_1",
      "author_type": "user",
      "message": "Bonjour...",
      "created_at": "2025-01-25T10:00:00Z"
    }
  ]
}
```

#### 4. Ajouter un message

```
POST /api/support/{team_slug}/tickets/{ticket_id}/messages
```

**Corps:**
```json
{
  "message": "Merci pour votre aide..."
}
```

#### 5. Statistiques

```
GET /api/support/{team_slug}/stats
```

**Réponse:**
```json
{
  "by_status": {
    "open": 5,
    "in_progress": 3,
    "resolved": 10
  },
  "by_priority": {
    "high": 2,
    "urgent": 1
  },
  "total": 18,
  "open": 8,
  "closed": 10,
  "avg_resolution_hours": 24.5
}
```

### Fonctionnalités spéciales

- **Priorité automatique:** Les tickets des équipes Pro sont automatiquement marqués "high"
- **Changement de statut intelligent:** Le statut change automatiquement selon l'auteur des messages
- **Messages internes:** Les messages marqués `is_internal` ne sont pas visibles par les utilisateurs
- **Statistiques détaillées:** Temps de résolution moyen, distribution par statut/priorité

---

## 3. Migration de base de données

**Fichier:** `/app/migrations/versions/20250125_add_additional_resources_and_support.py`

**Tables créées:**
- `additional_resource`
- `support_ticket`
- `support_message`

**Enums créés:**
- `resource_type` (ram, cpu, traffic, storage)
- `resource_status` (active, expired, cancelled)
- `ticket_priority` (low, normal, high, urgent)
- `ticket_status` (open, in_progress, waiting, resolved, closed)
- `ticket_category` (technical, billing, feature_request, bug_report, other)
- `message_author_type` (user, support, system)

---

## 4. Interface utilisateur (À compléter)

### Templates à créer

#### 1. Ressources additionnelles

**Fichier:** `/app/templates/team/partials/_settings-addons.html`

**Contenu suggéré:**
- Liste des ressources disponibles avec prix
- Ressources actuellement actives
- Bouton d'achat pour chaque type
- Date d'expiration
- Total des limites (plan + add-ons)

#### 2. Support

**Fichier:** `/app/templates/team/partials/_settings-support.html`

**Contenu suggéré:**
- Bouton "Nouveau ticket"
- Liste des tickets avec statut et priorité
- Filtres par statut/catégorie
- Badge "Pro" si plan Pro

**Fichier:** `/app/templates/support/ticket-detail.html`

**Contenu suggéré:**
- Détails du ticket
- Historique des messages
- Formulaire d'ajout de message
- Actions (résoudre, fermer)

#### 3. Dashboard avancé

**Fichier:** `/app/templates/team/partials/_dashboard-analytics.html`

**Contenu suggéré:**
- Graphiques d'utilisation (Chart.js)
- Tendances mensuelles
- Alertes d'utilisation
- Projets les plus consommateurs
- Ressources additionnelles actives

---

## 5. Cronjobs configurés

| Tâche | Planification | Description |
|-------|---------------|-------------|
| `check_inactive_projects` | 02h00 UTC | Désactive les projets inactifs |
| `cleanup_inactive_deployments` | 03h00 UTC | Nettoie les déploiements |
| `update_project_storage` | 04h00 UTC | Calcule l'espace disque |
| `expire_additional_resources` | 05h00 UTC | **Expire les ressources** |
| `check_usage_limits_task` | 06h00 UTC | Vérifie les limites |

---

## 6. Flux d'achat de ressources additionnelles

```
1. Utilisateur clique sur "Acheter RAM" (Plan Pro requis)
   ↓
2. Frontend appelle POST /api/resources/{team_slug}/purchase
   {
     "resource_type": "ram",
     "quantity": 2
   }
   ↓
3. Service calcule le prix (2 × 1€ = 2€)
   ↓
4. Service initie un paiement via PaymentService
   ↓
5. Création de la ressource (status: "active", expires_at: +30 jours)
   ↓
6. Redirection vers l'URL de paiement
   ↓
7. Utilisateur paie
   ↓
8. Webhook callback
   ↓
9. Ressource activée automatiquement
   ↓
10. Les limites totales sont mises à jour
```

---

## 7. Flux de support prioritaire

```
1. Utilisateur crée un ticket
   ↓
2. Si plan Pro → priority = "high" automatiquement
   ↓
3. Ticket créé avec status = "open"
   ↓
4. Premier message ajouté (description)
   ↓
5. Équipe support voit les tickets prioritaires
   ↓
6. Support répond
   ↓
7. Status change automatiquement à "in_progress"
   ↓
8. Utilisateur répond
   ↓
9. Status change à "waiting" (en attente de support)
   ↓
10. Support résout
   ↓
11. Status = "resolved", resolved_at enregistré
   ↓
12. Optionnel: Utilisateur ferme → status = "closed"
```

---

## 8. Intégration avec le système de paiement

Les ressources additionnelles utilisent le même système de paiement que les upgrades de plan:

1. Chaque achat génère un `Payment`
2. Le `payment_id` est lié à l'`AdditionalResource`
3. Une fois le paiement `completed`, la ressource devient active
4. Les ressources expirent après 30 jours (renouvellement mensuel)

---

## 9. TODO / Améliorations futures

### Court terme

- [ ] Créer les templates UI
- [ ] Implémenter le renouvellement automatique des ressources
- [ ] Ajouter des graphiques dans le dashboard
- [ ] Tests end-to-end

### Moyen terme

- [ ] Notifications email pour les tickets
- [ ] Webhooks pour les événements de support
- [ ] Export CSV des statistiques
- [ ] Analytics avancées avec graphiques historiques

### Long terme

- [ ] Chatbot de support IA
- [ ] Base de connaissance (FAQ auto-générée)
- [ ] Intégration Slack/Discord pour le support
- [ ] Prédiction de consommation de ressources

---

## 10. Configuration requise

Aucune variable d'environnement supplémentaire n'est nécessaire.

Les ressources additionnelles et le support utilisent la configuration existante.

---

## 11. Commandes utiles

### Appliquer la migration

```bash
cd app
alembic upgrade head
```

### Tester l'achat de ressources

```bash
curl -X POST http://localhost:8000/api/resources/my-team/purchase \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "resource_type": "ram",
    "quantity": 2
  }'
```

### Créer un ticket de support

```bash
curl -X POST http://localhost:8000/api/support/my-team/tickets \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "subject": "Problème de déploiement",
    "description": "Mon application ne démarre pas...",
    "category": "technical"
  }'
```

---

## 12. Notes importantes

1. **Ressources additionnelles:** Disponibles uniquement pour le plan Pro
2. **Priority Support:** Tous les plans peuvent créer des tickets, mais le Pro a la priorité automatique
3. **Expiration:** Les ressources expirent après 30 jours (renouvellement manuel requis)
4. **Limites:** Les add-ons s'ajoutent aux limites du plan de base
5. **Prix:** Basés sur les specs du fichier `pricing-specs.json`

---

## 13. Support technique

Pour toute question sur ces fonctionnalités:
- Documentation API: `/docs` (FastAPI Swagger)
- Code source: `/app/services/` et `/app/routers/`
- Tests: Créer des tests unitaires dans `/app/tests/`
