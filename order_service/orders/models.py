from django.db import models


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending",   "Pending"),
        ("confirmed", "Confirmed"),
        ("shipped",   "Shipped"),
        ("cancelled", "Cancelled"),
    ]

    # Plain integer — references User Service, not a real FK
    user_id = models.IntegerField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending")
    total_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders_order"

    def __str__(self):
        return f"Order #{self.id} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="items")

    # Plain integer — references Product Service, not a real FK
    product_id = models.IntegerField()

    # Snapshot values captured at the time the order was placed
    product_name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()

    class Meta:
        db_table = "orders_orderitem"

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.quantity}x {self.product_name}"
