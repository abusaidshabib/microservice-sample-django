import requests
from django.conf import settings


def _service_headers():
    """Return auth headers required for all inter-service calls."""
    return {"X-Service-Token": settings.INTERNAL_SERVICE_TOKEN}


def get_user(user_id):
    """
    Fetch a user from the User Service.
    Returns the user dict on success, or None if not found / service unreachable.
    """
    url = f"{settings.USER_SERVICE_URL}/api/users/{user_id}/"
    try:
        response = requests.get(url, headers=_service_headers(), timeout=5)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None
