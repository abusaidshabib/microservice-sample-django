import requests
from django.conf import settings
from django.core.cache import cache

_USER_CACHE_KEY = "svc:user:{user_id}"
_USER_CACHE_TTL = 300  # 5 minutes — reduces inter-service HTTP round-trips


def _service_headers():
    """Return auth headers required for all inter-service calls."""
    return {"X-Service-Token": settings.INTERNAL_SERVICE_TOKEN}


def get_user(user_id):
    """
    Fetch a user from the User Service.
    Results are cached in the Redis cluster to avoid repeated HTTP calls.
    Returns the user dict on success, or None if not found / service unreachable.
    """
    cache_key = _USER_CACHE_KEY.format(user_id=user_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    url = f"{settings.USER_SERVICE_URL}/api/users/{user_id}/"
    try:
        response = requests.get(url, headers=_service_headers(), timeout=5)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        user_data = response.json()
    except requests.exceptions.RequestException:
        return None

    cache.set(cache_key, user_data, timeout=_USER_CACHE_TTL)
    return user_data
