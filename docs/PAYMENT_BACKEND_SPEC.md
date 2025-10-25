# Spécifications du Backend de Paiement

Ce document décrit les endpoints que le backend de paiement externe **DOIT** implémenter pour s'intégrer avec Servelink.

---

## 🔐 Authentification

Tous les endpoints **doivent** être protégés par une API Key.

**Header requis :**
```
Authorization: Bearer {PAYMENT_API_KEY}
```

Le `PAYMENT_API_KEY` sera fourni lors de la configuration initiale.

---

## 📡 Endpoints requis

### 1. Initialiser un paiement

**Endpoint :**
```
POST /api/v1/payments/initiate
```

**Description :**
Crée une nouvelle transaction de paiement et génère l'URL de paiement.

**Headers :**
```
Authorization: Bearer {PAYMENT_API_KEY}
Content-Type: application/json
```

**Corps de la requête :**
```json
{
  "payment_id": "pm_abc123xyz",
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
  "callback_url": "https://servelink.com/api/payments/callback"
}
```

**Champs requis :**
- `payment_id` (string) : ID unique généré par Servelink
- `amount` (float) : Montant du paiement
- `currency` (string) : Code devise (EUR, USD, XOF, etc.)
- `payment_method` (string) : "mobile_money" ou "credit_card"
- `metadata` (object) : Informations contextuelles
- `callback_url` (string) : URL de callback pour notifier Servelink

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
- `external_payment_id` (string, **requis**) : ID unique du paiement dans votre système
- `status` (string, **requis**) : "pending" ou "processing"
- `payment_url` (string, **requis**) : URL où rediriger l'utilisateur
- `qr_code` (string, optionnel) : QR code en base64 pour paiement mobile
- `expires_at` (string, optionnel) : Date d'expiration ISO 8601

**Codes d'erreur :**
- `400` : Requête invalide
- `401` : API Key invalide
- `500` : Erreur interne

---

### 2. Vérifier le statut d'un paiement

**Endpoint :**
```
GET /api/v1/payments/{external_payment_id}/status
```

**Description :**
Récupère le statut actuel d'un paiement.

**Headers :**
```
Authorization: Bearer {PAYMENT_API_KEY}
```

**Paramètres URL :**
- `external_payment_id` : L'ID du paiement retourné lors de l'initialisation

**Réponse attendue (200 OK) :**
```json
{
  "external_payment_id": "ext_payment_xyz789",
  "status": "completed",
  "completed_at": "2025-01-25T10:15:30Z",
  "transaction_id": "txn_123456",
  "provider_reference": "ref_mobile_money_789",
  "metadata": {
    "provider": "Orange Money",
    "phone_number": "+221771234567"
  }
}
```

**Champs de la réponse :**
- `external_payment_id` (string, **requis**)
- `status` (string, **requis**) : Voir statuts ci-dessous
- `completed_at` (string, optionnel) : Date de complétion si status = "completed"
- `transaction_id` (string, optionnel) : ID de la transaction
- `provider_reference` (string, optionnel) : Référence du provider de paiement
- `metadata` (object, optionnel) : Informations supplémentaires

**Statuts possibles :**
- `pending` : En attente de paiement
- `processing` : Paiement en cours de traitement
- `completed` : Paiement réussi ✅
- `failed` : Paiement échoué ❌
- `cancelled` : Paiement annulé ⛔

**Codes d'erreur :**
- `401` : API Key invalide
- `404` : Paiement non trouvé
- `500` : Erreur interne

---

### 3. Annuler un paiement

**Endpoint :**
```
POST /api/v1/payments/{external_payment_id}/cancel
```

**Description :**
Annule un paiement en attente ou en cours de traitement.

**Headers :**
```
Authorization: Bearer {PAYMENT_API_KEY}
```

**Paramètres URL :**
- `external_payment_id` : L'ID du paiement à annuler

**Réponse attendue (200 OK) :**
```json
{
  "external_payment_id": "ext_payment_xyz789",
  "status": "cancelled",
  "cancelled_at": "2025-01-25T10:20:00Z"
}
```

**Champs de la réponse :**
- `external_payment_id` (string, **requis**)
- `status` (string, **requis**) : "cancelled"
- `cancelled_at` (string, **requis**) : Date d'annulation ISO 8601

**Codes d'erreur :**
- `400` : Paiement ne peut pas être annulé (déjà completed/failed)
- `401` : API Key invalide
- `404` : Paiement non trouvé
- `500` : Erreur interne

---

## 🔔 Webhook (Callback vers Servelink)

### Notifier Servelink d'un changement de statut

**Endpoint Servelink :**
```
POST https://servelink.com/api/payments/callback
```

**Quand appeler :**
- Quand le statut du paiement change
- Particulièrement important pour `completed`, `failed`, `cancelled`

**Headers :**
```
Content-Type: application/json
```

**Corps de la requête :**
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

**Champs requis :**
- `external_payment_id` (string, **requis**) : L'ID du paiement
- `status` (string, **requis**) : Le nouveau statut
- `metadata` (object, optionnel) : Informations supplémentaires

**Réponse de Servelink (200 OK) :**
```json
{
  "success": true,
  "payment_id": "pm_abc123xyz",
  "status": "completed"
}
```

**Notes importantes :**
- Le webhook doit être **idempotent** (peut être appelé plusieurs fois sans effet secondaire)
- Retry automatique recommandé en cas d'échec (backoff exponentiel)
- Timeout : 30 secondes max

---

## 🔄 Flux complet

### Scénario 1 : Paiement Mobile Money réussi

```
1. Servelink → Backend : POST /initiate
   {
     "payment_id": "pm_123",
     "amount": 3.0,
     "payment_method": "mobile_money"
   }

2. Backend → Servelink : 201 Created
   {
     "external_payment_id": "ext_789",
     "status": "pending",
     "payment_url": "https://pay.example.com/789"
   }

3. Utilisateur visite payment_url et paie

4. Backend → Servelink : POST /callback
   {
     "external_payment_id": "ext_789",
     "status": "completed",
     "metadata": {"transaction_id": "txn_456"}
   }

5. Servelink active le plan Pro automatiquement
```

### Scénario 2 : Paiement annulé

```
1-3. Même chose que ci-dessus

4. Utilisateur annule ou timeout

5. Backend → Servelink : POST /callback
   {
     "external_payment_id": "ext_789",
     "status": "cancelled"
   }
```

---

## 💳 Méthodes de paiement supportées

### Mobile Money

**Providers attendus :**
- Orange Money (Sénégal, Côte d'Ivoire, Mali, etc.)
- MTN Mobile Money
- Moov Money
- Wave
- Free Money

**Flow :**
1. Génération d'un code de paiement
2. Affichage QR code + instructions
3. Utilisateur paie via son app mobile
4. Callback automatique

### Credit Card

**Providers attendus :**
- Stripe
- PayPal
- Visa/Mastercard via gateway local

**Flow :**
1. Redirection vers page de paiement sécurisée
2. Saisie des informations de carte
3. Validation 3D Secure si requis
4. Callback automatique

---

## 🧪 Environnement de test

### Sandbox

Le backend **DOIT** fournir un environnement de test avec :

- URL sandbox : `https://sandbox-payment.example.com`
- API Key de test
- Paiements simulés (complétion instantanée)
- Pas de vraie transaction

### Test Data

**Montants de test :**
- `0.01 EUR` → Succès immédiat
- `0.02 EUR` → Échec immédiat
- `0.03 EUR` → Timeout/Annulation
- `3.00 EUR` → Succès après 30 secondes

---

## 🔒 Sécurité

### Recommandations

1. **HTTPS uniquement** pour tous les endpoints
2. **Rate limiting** : Max 100 requêtes/minute par API Key
3. **Signature des webhooks** (optionnel mais recommandé)
4. **IP Whitelisting** pour le callback (optionnel)
5. **Logs d'audit** pour toutes les transactions

### Signature de webhook (optionnel)

Si implémenté, ajouter un header :
```
X-Payment-Signature: sha256=abc123...
```

Calculé avec :
```
HMAC-SHA256(webhook_secret, request_body)
```

---

## 📊 Monitoring

### Métriques à exposer

Le backend **DEVRAIT** exposer :

1. **Taux de succès** : % de paiements completed vs total
2. **Temps moyen** : Durée moyenne pending → completed
3. **Disponibilité** : Uptime de l'API
4. **Latence** : P50, P95, P99 des endpoints

### Health Check

**Endpoint :**
```
GET /health
```

**Réponse (200 OK) :**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-01-25T10:00:00Z"
}
```

---

## 📝 Exemples de code

### Python (FastAPI)

```python
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import secrets

app = FastAPI()
API_KEY = "your_secret_api_key"

class InitiatePaymentRequest(BaseModel):
    payment_id: str
    amount: float
    currency: str
    payment_method: str
    metadata: dict
    callback_url: str

@app.post("/api/v1/payments/initiate")
async def initiate_payment(
    request: InitiatePaymentRequest,
    authorization: str = Header(...)
):
    # Vérifier l'API Key
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "Invalid API Key")
    
    # Générer un ID externe
    external_id = f"ext_{secrets.token_hex(8)}"
    
    # Créer le paiement dans votre DB
    # ...
    
    # Générer l'URL de paiement
    payment_url = f"https://pay.example.com/{external_id}"
    
    return {
        "external_payment_id": external_id,
        "status": "pending",
        "payment_url": payment_url,
        "qr_code": "data:image/png;base64,...",  # Optionnel
        "expires_at": "2025-01-25T11:00:00Z"
    }

@app.get("/api/v1/payments/{external_payment_id}/status")
async def get_status(
    external_payment_id: str,
    authorization: str = Header(...)
):
    # Vérifier l'API Key
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "Invalid API Key")
    
    # Récupérer le paiement depuis votre DB
    # payment = get_payment(external_payment_id)
    
    return {
        "external_payment_id": external_payment_id,
        "status": "completed",  # ou pending, processing, etc.
        "completed_at": "2025-01-25T10:15:30Z",
        "transaction_id": "txn_123456"
    }

@app.post("/api/v1/payments/{external_payment_id}/cancel")
async def cancel_payment(
    external_payment_id: str,
    authorization: str = Header(...)
):
    # Vérifier l'API Key
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "Invalid API Key")
    
    # Annuler le paiement dans votre DB
    # ...
    
    return {
        "external_payment_id": external_payment_id,
        "status": "cancelled",
        "cancelled_at": "2025-01-25T10:20:00Z"
    }
```

---

## ✅ Checklist d'implémentation

- [ ] Endpoint POST /initiate implémenté
- [ ] Endpoint GET /status implémenté
- [ ] Endpoint POST /cancel implémenté
- [ ] Webhook vers Servelink implémenté
- [ ] HTTPS activé
- [ ] Authentification par API Key
- [ ] Environnement sandbox disponible
- [ ] Mobile Money intégré
- [ ] Credit Card intégré (optionnel)
- [ ] Tests automatisés
- [ ] Documentation API
- [ ] Monitoring et logs
- [ ] Rate limiting
- [ ] Health check endpoint

---

## 📞 Contact

Pour toute question technique :
- Email : tech@servelink.com
- Documentation : https://docs.servelink.com/payment-integration
- Support : https://support.servelink.com
