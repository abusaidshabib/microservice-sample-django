from decimal import Decimal
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Order, OrderItem
from .serializers import OrderSerializer, CreateOrderSerializer
from .services import get_user
from .tasks import send_order_confirmation

# ── cache key helpers ─────────────────────────────────────────────────────────
_LIST_KEY = "orders:list"
_DETAIL_KEY = "orders:detail:{order_id}"
_LIST_TTL = 60       # 1 minute — refreshed often as new orders arrive
_DETAIL_TTL = 300    # 5 minutes — order details rarely change after creation


def _detail_key(order_id) -> str:
    return _DETAIL_KEY.format(order_id=order_id)


def _bust_order_cache(order_id=None) -> None:
    """Invalidate list cache and, optionally, a single detail cache."""
    keys = [_LIST_KEY]
    if order_id is not None:
        keys.append(_detail_key(order_id))
    cache.delete_many(keys)


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class OrderListView(APIView):
    def get(self, request):
        cached = cache.get(_LIST_KEY)
        if cached is not None:
            return Response(cached)

        orders = Order.objects.prefetch_related("items").all()
        data = OrderSerializer(orders, many=True).data
        cache.set(_LIST_KEY, data, timeout=_LIST_TTL)
        return Response(data)

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # 1. Validate the user exists in User Service
        user = get_user(data["user_id"])
        if not user:
            return Response(
                {"error": f"User {data['user_id']} not found in User Service."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. Calculate total price
        total = sum(
            Decimal(str(item["unit_price"])) * item["quantity"]
            for item in data["items"]
        )

        # 3. Save the order
        order = Order.objects.create(
            user_id=data["user_id"],
            total_price=total,
        )

        # 4. Save each item (snapshot product data at purchase time)
        for item in data["items"]:
            OrderItem.objects.create(
                order=order,
                product_id=item["product_id"],
                product_name=item["product_name"],
                unit_price=item["unit_price"],
                quantity=item["quantity"],
            )

        # 5. Invalidate list cache so the new order appears immediately.
        _bust_order_cache()

        # 6. Fire async task — does NOT block the response
        send_order_confirmation.delay(
            user_email=user.get("email", ""),
            order_id=order.id,
        )

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderDetailView(APIView):
    def get(self, request, order_id):
        cached = cache.get(_detail_key(order_id))
        if cached is not None:
            return Response(cached)

        try:
            order = Order.objects.prefetch_related("items").get(id=order_id)
        except Order.DoesNotExist:
            return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

        data = OrderSerializer(order).data
        cache.set(_detail_key(order_id), data, timeout=_DETAIL_TTL)
        return Response(data)

    def patch(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get("status")
        valid_statuses = [s[0] for s in Order.STATUS_CHOICES]
        if new_status not in valid_statuses:
            return Response(
                {"error": f"Invalid status. Choose from: {valid_statuses}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order.status = new_status
        order.save()

        # Invalidate both list and detail caches so callers see the new status.
        _bust_order_cache(order_id=order_id)

        return Response(OrderSerializer(order).data)
