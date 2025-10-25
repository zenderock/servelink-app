# Intégration du système de paiement

Ce document décrit l'intégration entre Servelink et le backend de paiement externe, ainsi que les endpoints disponibles pour gérer les paiements et le tracking de l'utilisation.

## Configuration

### Variables d'environnement

Ajoutez ces variables au fichier `.env` :

```bash
# Backend de paiement
PAYMENT_BACKEND_URL=http://localhost:8001
PAYMENT_API_KEY=your_secret_api_key_here
BASE_URL=https://your-domain.com
```

## Endpoints backend de paiement (Backend externe)

### 1. Initialisation d'un paiement

**Endpoint appelé par Servelink :**
```
POST /api/v1/payments/initiate
```

**Headers requis :**
```
Authorization: Bearer {PAYMENT_API_KEY}
Content-Type: application/json
```

**Corps de la requête :**
```json
{
  "payment_id": "abc123xyz",
  "amount": 3.0,
  "currency": "EUR",
  "payment_method": "mobile_money",
  "metadata": {
    "description": "Upgrade to Pro plan",
    "team_id": "team_abc123",
    "team_name": "My Team",
    "user_id": 123,
    "user_email": "user@example.com",
    "plan_upgrade": true,
    "new_plan": "pay_as_you_go"
  },
  "callback_url": "https://your-domain.com/api/payments/callback"
}
```

**Réponse attendue (201 Created) :**
```json
{
  "external_payment_id": "ext_payment_xyz789",
  "status": "pending",
  "payment_url": "https://payment.example.com/pay/xyz789",
  "qr_code": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
  "expires_at": "2025-01-25T11:00:00Z"
}
```

**Champs de la réponse :**
- `external_payment_id` : ID unique généré par le backend de paiement
- `status` : Statut initial du paiement (`pending`, `processing`)
- `payment_url` : URL de paiement pour redirection de l'utilisateur
- `qr_code` : QR code en base64 pour paiement mobile (optionnel)
- `expires_at` : Date d'expiration du lien de paiement (optionnel)

---

### 2. Vérification du statut d'un paiement

**Endpoint appelé par Servelink :**
```
GET /api/v1/payments/{external_payment_id}/status
```

**Headers requis :**
```
Authorization: Bearer {PAYMENT_API_KEY}
```

**Réponse attendue (200 OK) :**
```json
{
  "external_payment_id": "ext_payment_xyz789",
  "status": "completed",
  "completed_at": "2025-01-25T10:15:30Z",
  "transaction_id": "txn_123456",
  "provider_reference": "ref_mobile_money_789"
}
```

**Valeurs possibles pour `status` :**
- `pending` : Paiement en attente
- `processing` : Paiement en cours de traitement
- `completed` : Paiement réussi
- `failed` : Paiement échoué
- `cancelled` : Paiement annulé

---

### 3. Annulation d'un paiement

**Endpoint appelé par Servelink :**
```
POST /api/v1/payments/{external_payment_id}/cancel
```

**Headers requis :**
```
Authorization: Bearer {PAYMENT_API_KEY}
```

**Réponse attendue (200 OK) :**
```json
{
  "external_payment_id": "ext_payment_xyz789",
  "status": "cancelled",
  "cancelled_at": "2025-01-25T10:20:00Z"
}
```

---

### 4. Callback webhook (appelé par le backend de paiement)

**Endpoint fourni par Servelink :**
```
POST https://your-domain.com/api/payments/callback
```

**Headers requis :**
```
Content-Type: application/json
```

**Corps de la requête (envoyé par le backend de paiement) :**
```json
{
  "external_payment_id": "ext_payment_xyz789",
  "status": "completed",
  "metadata": {
    "transaction_id": "txn_123456",
    "provider_reference": "ref_mobile_money_789",
    "provider": "Orange Money",
    "phone_number": "+221771234567",
    "completed_at": "2025-01-25T10:15:30Z"
  }
}
```

**Réponse de Servelink (200 OK) :**
```json
{
  "success": true,
  "payment_id": "abc123xyz",
  "status": "completed"
}
```

---

## Endpoints Servelink (API publique)

### 1. Initialiser un paiement

```
POST /api/payments/{team_slug}/initiate
```

**Authentication :** Bearer token requis

**Corps de la requête :**
```json
{
  "amount": 3.0,
  "payment_method": "mobile_money",
  "plan_upgrade": true,
  "new_plan": "pay_as_you_go",
  "description": "Upgrade to Pro plan"
}
```

**Réponse (200 OK) :**
```json
{
  "payment_id": "abc123xyz",
  "external_payment_id": "ext_payment_xyz789",
  "status": "pending",
  "amount": 3.0,
  "currency": "EUR",
  "payment_url": "https://payment.example.com/pay/xyz789",
  "qr_code": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
  "created_at": "2025-01-25T10:00:00Z"
}
```

---

### 2. Historique des paiements

```
GET /api/payments/{team_slug}/history
```

**Authentication :** Bearer token requis

**Réponse (200 OK) :**
```json
{
  "payments": [
    {
      "payment_id": "abc123xyz",
      "amount": 3.0,
      "currency": "EUR",
      "payment_method": "mobile_money",
      "status": "completed",
      "metadata": {
        "description": "Upgrade to Pro plan",
        "new_plan": "pay_as_you_go",
        "transaction_id": "txn_123456"
      },
      "created_at": "2025-01-25T10:00:00Z",
      "completed_at": "2025-01-25T10:15:30Z"
    }
  ]
}
```

---

### 3. Vérifier le statut d'un paiement

```
GET /api/payments/{payment_id}/status
```

**Authentication :** Bearer token requis

**Réponse (200 OK) :**
```json
{
  "payment_id": "abc123xyz",
  "status": "completed",
  "amount": 3.0,
  "currency": "EUR",
  "created_at": "2025-01-25T10:00:00Z",
  "completed_at": "2025-01-25T10:15:30Z"
}
```

---

### 4. Annuler un paiement

```
POST /api/payments/{payment_id}/cancel
```

**Authentication :** Bearer token requis

**Réponse (200 OK) :**
```json
{
  "payment_id": "abc123xyz",
  "status": "cancelled"
}
```

---

## Endpoints de tracking d'utilisation

Ces endpoints sont utilisés en interne pour suivre l'utilisation du trafic et du stockage.

### Service UsageTrackingService

#### Enregistrer le trafic
```python
await UsageTrackingService.record_traffic(
    project_id="project_123",
    bytes_transferred=1024000,  # 1MB
    db=db
)
```

#### Mettre à jour le stockage
```python
await UsageTrackingService.update_storage(
    project_id="project_123",
    storage_bytes=52428800,  # 50MB
    db=db
)
```

#### Récupérer les statistiques du mois en cours
```python
usage = await UsageTrackingService.get_current_month_usage(
    project_id="project_123",
    db=db
)
# Retourne:
# {
#     "traffic_bytes": 1024000,
#     "traffic_mb": 1.0,
#     "traffic_gb": 0.001,
#     "storage_bytes": 52428800,
#     "storage_mb": 50.0,
#     "storage_gb": 0.05
# }
```

#### Vérifier les limites d'utilisation
```python
within_limits, error_message = await UsageTrackingService.check_usage_limits(
    project=project,
    team=team,
    db=db
)
```

#### Récupérer le résumé d'utilisation d'une équipe
```python
summary = await UsageTrackingService.get_usage_summary(
    team_id="team_123",
    db=db
)
# Retourne:
# {
#     "plan": {
#         "name": "free",
#         "display_name": "Free",
#         "max_traffic_gb": 5,
#         "max_storage_mb": 100
#     },
#     "usage": {
#         "traffic_bytes": 3145728000,
#         "traffic_mb": 3000.0,
#         "traffic_gb": 3.0,
#         "storage_bytes": 73400320,
#         "storage_mb": 70.0,
#         "storage_gb": 0.07
#     },
#     "limits": {
#         "traffic": {
#             "used_gb": 3.0,
#             "limit_gb": 5,
#             "percentage": 60.0
#         },
#         "storage": {
#             "used_mb": 70.0,
#             "limit_mb": 100,
#             "percentage": 70.0
#         }
#     }
# }
```

---

## Flux de paiement complet

### 1. Initialisation du paiement (Frontend → Servelink)
L'utilisateur clique sur "Upgrade to Pro" dans l'interface.

**Requête :**
```http
POST /api/payments/my-team/initiate
Content-Type: application/json
Authorization: Bearer {user_token}

{
  "amount": 3.0,
  "payment_method": "mobile_money",
  "plan_upgrade": true,
  "new_plan": "pay_as_you_go",
  "description": "Upgrade to Pro plan"
}
```

### 2. Servelink → Backend de paiement
Servelink transmet la requête au backend de paiement.

**Requête :**
```http
POST http://payment-backend:8001/api/v1/payments/initiate
Content-Type: application/json
Authorization: Bearer {PAYMENT_API_KEY}

{
  "payment_id": "pm_abc123xyz",
  "amount": 3.0,
  "currency": "EUR",
  "payment_method": "mobile_money",
  "metadata": {...},
  "callback_url": "https://servelink.com/api/payments/callback"
}
```

### 3. Backend de paiement → Servelink (réponse)
Le backend retourne les informations de paiement.

**Réponse :**
```json
{
  "external_payment_id": "ext_xyz789",
  "status": "pending",
  "payment_url": "https://pay.example.com/xyz789",
  "qr_code": "data:image/png;base64,..."
}
```

### 4. Servelink → Frontend (réponse)
Servelink retourne les informations au frontend.

**Réponse :**
```json
{
  "payment_id": "pm_abc123xyz",
  "external_payment_id": "ext_xyz789",
  "status": "pending",
  "payment_url": "https://pay.example.com/xyz789",
  "qr_code": "data:image/png;base64,..."
}
```

### 5. Frontend redirige l'utilisateur
Le frontend affiche le QR code ou redirige vers `payment_url`.

### 6. Backend de paiement → Servelink (callback)
Quand le paiement est complété, le backend appelle le webhook.

**Requête :**
```http
POST https://servelink.com/api/payments/callback
Content-Type: application/json

{
  "external_payment_id": "ext_xyz789",
  "status": "completed",
  "metadata": {
    "transaction_id": "txn_123456",
    "provider_reference": "ref_789"
  }
}
```

### 7. Servelink active le plan Pro
Servelink met à jour le statut du paiement et active le plan Pro pour l'équipe.

---

## Modèles de données

### Payment
```python
class Payment:
    id: str                      # ID interne Servelink
    team_id: str                 # ID de l'équipe
    external_payment_id: str     # ID du backend de paiement
    amount: float                # Montant
    currency: str                # Devise (EUR)
    payment_method: str          # mobile_money | credit_card
    status: str                  # pending | processing | completed | failed | cancelled
    metadata: dict               # Métadonnées
    created_at: datetime
    updated_at: datetime
    completed_at: datetime       # Nullable
```

### ProjectUsage
```python
class ProjectUsage:
    id: str
    project_id: str
    month: int                   # 1-12
    year: int
    traffic_bytes: int           # Octets transférés
    storage_bytes: int           # Espace disque utilisé
    created_at: datetime
    updated_at: datetime
```

---

## Exemple d'implémentation backend de paiement (Mock)

Voici un exemple simple de ce que le backend de paiement devrait implémenter :

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

app = FastAPI()

class InitiatePaymentRequest(BaseModel):
    payment_id: str
    amount: float
    currency: str
    payment_method: str
    metadata: dict
    callback_url: str

@app.post("/api/v1/payments/initiate")
async def initiate_payment(request: InitiatePaymentRequest):
    # Générer un ID externe
    external_id = f"ext_{request.payment_id}"
    
    # Créer le lien de paiement
    payment_url = f"https://payment.example.com/pay/{external_id}"
    
    # Simuler un traitement asynchrone
    # Dans la vraie vie, ce serait un appel à un provider (Orange Money, Wave, etc.)
    
    return {
        "external_payment_id": external_id,
        "status": "pending",
        "payment_url": payment_url,
        "qr_code": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
    }

@app.get("/api/v1/payments/{external_payment_id}/status")
async def get_payment_status(external_payment_id: str):
    # Dans la vraie vie, vérifier le statut auprès du provider
    return {
        "external_payment_id": external_payment_id,
        "status": "completed",
        "completed_at": "2025-01-25T10:15:30Z",
        "transaction_id": "txn_123456"
    }

@app.post("/api/v1/payments/{external_payment_id}/cancel")
async def cancel_payment(external_payment_id: str):
    # Annuler le paiement
    return {
        "external_payment_id": external_payment_id,
        "status": "cancelled",
        "cancelled_at": "2025-01-25T10:20:00Z"
    }

# Simuler un callback après paiement réussi
async def simulate_payment_completed(external_payment_id: str, callback_url: str):
    async with httpx.AsyncClient() as client:
        await client.post(callback_url, json={
            "external_payment_id": external_payment_id,
            "status": "completed",
            "metadata": {
                "transaction_id": "txn_123456",
                "provider_reference": "ref_789"
            }
        })
```

---

## Notes importantes

1. **Sécurité** : Le `PAYMENT_API_KEY` doit être sécurisé et ne jamais être exposé côté client.

2. **Idempotence** : Les endpoints doivent être idempotents pour gérer les retries.

3. **Timeout** : Les appels au backend de paiement ont un timeout de 30 secondes.

4. **Retry** : En cas d'échec, Servelink ne fait pas de retry automatique. Le statut du paiement peut être vérifié manuellement.

5. **Webhooks** : Le callback doit être sécurisé (IP whitelisting, signature, etc.).

6. **Testing** : Utilisez des montants de test (0.01 EUR) pour les tests en développement.
