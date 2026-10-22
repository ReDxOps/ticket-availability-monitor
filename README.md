# 🎟️ Dream Nation 2026 — Ticket Availability Monitor

Service autonome de surveillance 24h/24 en lecture seule pour la billetterie officielle [See Tickets Resell Dream Nation 2026](https://resell.seetickets.com/dreamnation2026/), alertant instantanément sur iPhone via **Telegram** dès qu'au moins 1 billet **PASS 1 JOUR VENDREDI** (30 octobre 2026) est réellement disponible à l'achat, avec priorité pour les offres de **2 billets ou plus**.

---

## 📋 Fonctionnalités clés

- **Surveillance passive légère & autorisée :** Interroge l'endpoint public `/api/adverts_search` toutes les 10 secondes (requête ultra-légère de ~270 octets en HTTP/2, temps de réponse <300 ms).
- **Distinction stricte des états :**
  - `AVAILABLE` : Billet réellement achetable (bouton « Ajouter au panier » actif). Déclenche l'alerte !
  - `IN_CART` : Billet présent dans le panier d'un autre acheteur. Surveillance silencieuse sans fausse alerte.
  - `SOLD_OUT` : Épuisé.
  - `UNKNOWN` : Erreur réseau, timeout ou code 5xx (jamais interprété comme une disponibilité).
- **Détection des retours de panier :** Dès qu'un panier expire sur la plateforme sans finalisation d'achat, le billet redevient `AVAILABLE` et déclenche une alerte spéciale *« Billet de nouveau disponible (panier expiré) »*.
- **Déduplication intelligente :** Suivi d'état en base SQLite pour ne jamais spammer l'utilisateur sur une même annonce non modifiée.
- **Lien direct vérifié :** Chaque notification contient un lien direct ciblant l'identifiant exact de l'annonce (`?advert={id}`).
- **Résilience & éthique :**
  - **Aucun achat automatique, aucune mise au panier, aucun paiement.**
  - Backoff exponentiel sur HTTP 429 (Rate Limit) et 5xx avec respect de l'en-tête `Retry-After`.
  - Alertes techniques distinctes en cas de coupure prolongée du réseau.
  - Arrêt automatique passé la date de l'événement.

---

## 🛠️ Installation et Configuration

### 1. Cloner ou naviguer dans le projet
```bash
cd /Users/remy/Documents/ticket-availability-monitor
```

### 2. Configurer les variables d'environnement
Copiez le modèle de configuration :
```bash
cp .env.example .env
```
Éditez ensuite `.env` pour renseigner vos identifiants Telegram :
```env
TELEGRAM_BOT_TOKEN="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
TELEGRAM_CHAT_ID="987654321"
```

> **Comment obtenir vos identifiants Telegram ?**
> 1. Ouvrez Telegram et cherchez `@BotFather` pour créer votre bot (`/newbot`) et obtenir votre `TELEGRAM_BOT_TOKEN`.
> 2. Lancez une conversation avec votre bot (cliquez sur `Démarrer`).
> 3. Cherchez `@userinfobot` ou ouvrez `https://api.telegram.org/bot<TOKEN>/getUpdates` pour obtenir votre `TELEGRAM_CHAT_ID`.

---

## 🚀 Utilisation en Local (Python)

### 1. Activer l'environnement virtuel
```bash
source .venv/bin/activate
```

### 2. Tester les notifications Telegram
Un script dédié permet de valider instantanément que votre bot et votre chat ID fonctionnent :
```bash
python scripts/test_notification.py
```
*Vous devez recevoir immédiatement une notification de test sur votre iPhone.*

### 3. Lancer la suite de tests unitaires
```bash
pytest -v
```

### 4. Démarrer le moniteur en local
```bash
python -m src.monitor
```
Pour arrêter : faites `Ctrl + C`. Le service s'éteint proprement en fermant la base SQLite et les sessions HTTP.

---

## 🐳 Déploiement avec Docker Compose (Serveur / VPS)

Le projet dispose d'une image Docker sécurisée (utilisateur non-root, healthcheck, volume persistant pour la base SQLite).

### 1. Démarrer le conteneur en arrière-plan
```bash
docker compose up -d --build
```

### 2. Consulter les logs en temps réel
```bash
docker compose logs -f monitor
```

### 3. Vérifier l'état de santé du conteneur
```bash
docker compose ps
```

### 4. Arrêter le moniteur
```bash
docker compose down
```

---

## 🗄️ Persistance et Données SQLite

Les données sont persistées dans `./data/monitor.db` :
- `advert_state` : État courant de chaque annonce See Tickets.
- `state_history` : Historique horodaté des transitions (`AVAILABLE`, `IN_CART`, etc.).
- `notification_log` : Registre des alertes envoyées pour la déduplication.

Pour inspecter la base de données :
```bash
sqlite3 data/monitor.db "SELECT advert_id, state, nb_available, nb_cart, updated_at FROM advert_state;"
```

---

## ⚙️ Paramètres disponibles dans `.env`

| Variable | Défaut | Description |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `10` | Intervalle de polling en secondes (minimum 5) |
| `TARGET_TICKETS_COUNT` | `2` | Seuil pour priorisation d'alerte (`🚨 2+ BILLETS DISPONIBLES`) |
| `CUTOFF_DATE` | `2026-10-31T05:00:00+02:00` | Date d'arrêt automatique du moniteur |
| `CONSECUTIVE_ERRORS_THRESHOLD` | `10` | Nombre d'erreurs consécutives avant alerte technique |
| `LOG_LEVEL` | `INFO` | Niveau de verbosité (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
