from django.conf import settings
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import User
from .serializers import UserSerializer, RegisterSerializer

# ── cache key helpers ─────────────────────────────────────────────────────────
_LIST_KEY = "users:list"
_DETAIL_KEY = "users:detail:{user_id}"
_LIST_TTL = 120      # 2 minutes
_DETAIL_TTL = 600    # 10 minutes — user records rarely change


def _detail_key(user_id) -> str:
    return _DETAIL_KEY.format(user_id=user_id)


def _require_service_token(request):
    """Return True if the request carries a valid inter-service token."""
    token = request.headers.get("X-Service-Token", "")
    return token == settings.INTERNAL_SERVICE_TOKEN


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class RegisterView(APIView):
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            # Invalidate user list so the new user appears immediately.
            cache.delete(_LIST_KEY)
            return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserDetailView(APIView):
    def get(self, request, user_id):
        if not _require_service_token(request):
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        cached = cache.get(_detail_key(user_id))
        if cached is not None:
            return Response(cached)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        data = UserSerializer(user).data
        cache.set(_detail_key(user_id), data, timeout=_DETAIL_TTL)
        return Response(data)


class UserListView(APIView):
    def get(self, request):
        cached = cache.get(_LIST_KEY)
        if cached is not None:
            return Response(cached)

        users = User.objects.all()
        data = UserSerializer(users, many=True).data
        cache.set(_LIST_KEY, data, timeout=_LIST_TTL)
        return Response(data)
