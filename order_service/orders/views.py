from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Order, OrderItem
from .serializers import OrderSerializer, CreateOrderSerializer
from .services import get_user
from .tasks import send_order_confirmation


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class OrderListView(APIView):
    def get(self, request):
        orders = Order.objects.prefetch_related("items").all()
        return Response(OrderSerializer(orders, many=True).data)

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

        # 5. Fire async task — does NOT block the response
        send_order_confirmation.delay(
            user_email=user.get("email", ""),
            order_id=order.id,
        )

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderDetailView(APIView):
    def get(self, request, order_id):
        try:
            order = Order.objects.prefetch_related("items").get(id=order_id)
        except Order.DoesNotExist:
            return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(OrderSerializer(order).data)

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
        return Response(OrderSerializer(order).data)
