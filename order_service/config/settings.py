import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
DEBUG = os.environ.get("DEBUG", "True") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "orders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "db_orders"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery (standalone Redis — separate from the cache cluster)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL


# ── Redis Cluster cache ───────────────────────────────────────────────────
def _parse_cluster_nodes(raw: str) -> list[dict]:
    """Parse 'host1:port,host2:port,...' into a list of node dicts."""
    nodes = []
    for entry in raw.split(","):
        host, _, port = entry.strip().partition(":")
        nodes.append({"host": host, "port": int(port or 6379)})
    return nodes


_CLUSTER_NODES_RAW = os.environ.get(
    "REDIS_CLUSTER_NODES",
    "redis-node-0:6379,redis-node-1:6379,redis-node-2:6379,"
    "redis-node-3:6379,redis-node-4:6379,redis-node-5:6379",
)
_CLUSTER_PASSWORD = os.environ.get("REDIS_CLUSTER_PASSWORD", "")

CACHES = {
    "default": {
        "BACKEND": "config.cluster_cache.RedisClusterCache",
        "KEY_PREFIX": "order_svc",
        # Default TTL for cache entries (seconds).
        "TIMEOUT": 300,
        "OPTIONS": {
            "startup_nodes": _parse_cluster_nodes(_CLUSTER_NODES_RAW),
            "password": _CLUSTER_PASSWORD,
            # Connection timeouts (seconds).
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            # Max connections per node in the pool.
            "max_connections": 50,
            # Spread read commands across replicas.
            "read_from_replicas": True,
        },
    }
}

# Other services
USER_SERVICE_URL = os.environ.get(
    "USER_SERVICE_URL", "http://user-service:8001")

# Shared secret for inter-service calls — must match across all services
INTERNAL_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN", "")
if not INTERNAL_SERVICE_TOKEN:
    raise RuntimeError(
        "INTERNAL_SERVICE_TOKEN environment variable is not set")
