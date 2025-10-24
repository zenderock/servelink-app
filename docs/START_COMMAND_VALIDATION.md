# Validation des commandes de démarrage

## Vue d'ensemble

Le système valide automatiquement les commandes de démarrage pour empêcher les utilisateurs de spécifier plusieurs workers, ce qui pourrait causer des problèmes de ressources.

## Serveurs supportés

La validation détecte et bloque les configurations multi-workers pour les serveurs suivants :

### 1. **Gunicorn** (Python WSGI)
```bash
# ❌ Bloqué
gunicorn -w 2 app:app
gunicorn --workers 4 app:app

# ✅ Autorisé
gunicorn app:app
gunicorn -w 1 app:app
gunicorn --workers 1 app:app
```

### 2. **Uvicorn** (Python ASGI)
```bash
# ❌ Bloqué
uvicorn --workers 3 app:app

# ✅ Autorisé
uvicorn app:app
```

### 3. **Hypercorn** (Python ASGI)
```bash
# ❌ Bloqué
hypercorn -w 2 app:app
hypercorn --workers 5 app:app

# ✅ Autorisé
hypercorn app:app
hypercorn -w 1 app:app
```

### 4. **Daphne** (Django Channels)
```bash
# ❌ Bloqué
daphne -w 3 asgi:application

# ✅ Autorisé
daphne asgi:application
```

### 5. **Waitress** (Python WSGI)
```bash
# ❌ Bloqué
waitress-serve --threads 8 app:app

# ✅ Autorisé
waitress-serve app:app
waitress-serve --threads 1 app:app
```

### 6. **Puma** (Ruby)
```bash
# ❌ Bloqué
puma -w 5 config.ru
puma --workers 3 config.ru

# ✅ Autorisé
puma config.ru
puma -w 1 config.ru
```

### 7. **Unicorn** (Ruby)
```bash
# ❌ Bloqué
unicorn -w 4 config.ru

# ✅ Autorisé
unicorn config.ru
unicorn -w 1 config.ru
```

## Message d'erreur

Quand une commande avec plusieurs workers est détectée, l'utilisateur reçoit un message d'erreur :

```
Multiple workers are not allowed. Please use a single worker for [Server Name]. 
Remove the workers option or set it to 1.
```

## Implémentation technique

La validation utilise des expressions régulières pour détecter les patterns suivants :
- `-w [2-9]` ou `-w [10+]`
- `--workers [2-9]` ou `--workers [10+]`
- `--threads [2-9]` ou `--threads [10+]` (pour Waitress)

Le validateur est appliqué dans :
- `ProjectBuildAndProjectDeployForm` (création de projet)
- `ProjectSettingsForm` (modification des paramètres)

## Pourquoi cette limitation ?

1. **Gestion des ressources** : Chaque worker consomme de la mémoire et du CPU
2. **Prédictibilité** : Un seul worker permet un meilleur contrôle des ressources allouées
3. **Simplicité** : Évite les problèmes de configuration complexes
4. **Coûts** : Limite la consommation de ressources par projet

## Alternatives

Pour gérer plus de charge, les utilisateurs peuvent :
1. Augmenter les ressources CPU/RAM du projet
2. Utiliser le scaling horizontal avec plusieurs instances
3. Optimiser le code de l'application
