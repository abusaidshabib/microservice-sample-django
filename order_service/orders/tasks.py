from celery import shared_task


@shared_task
def send_order_confirmation(user_email, order_id):
    """
    Placeholder async task — in a real project this would call an Email Service.
    Runs in the background via Celery so the order API responds immediately.
    """
    print(
        f"[email] Sending confirmation for order #{order_id} to {user_email}")
