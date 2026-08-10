from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import Notification


def send_notification(company,user, title, message, notification_type):
    # Save notification in database
    print("========== send_notification() CALLED ==========")
    print("User:", user.email)




    notification = Notification.objects.create(
        company=company,
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
    )
    print("Notification saved in DB")

    # Send notification through WebSocket
    channel_layer = get_channel_layer()
    print(f"Sending to group: user_{user.id}")

    try:
        async_to_sync(channel_layer.group_send)(
            f"user_{user.id}",
            {
                "type": "send_notification",
                "title": title,
                "message": message,
                "notification_type": notification_type,
                "id": notification.id,
                "created_at": notification.created_at.isoformat(),
            },
        )
        print("✅ group_send completed")

    except Exception as e:
        import traceback
        print("❌ group_send FAILED")
        traceback.print_exc()
        raise

    return notification