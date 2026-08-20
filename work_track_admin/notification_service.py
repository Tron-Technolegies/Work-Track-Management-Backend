from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import Notification


def send_notification(company, user, title, message, notification_type):
    print("========== send_notification() CALLED ==========")
    print("User:", user.email)

    # 1. Always save notification in database
    notification = Notification.objects.create(
        company=company,
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
    )

    print("Notification saved in DB")

    # 2. Try real-time WebSocket notification
    try:
        channel_layer = get_channel_layer()

        print(f"Sending to group: user_{user.id}")

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

        print("✅ WebSocket notification sent")

    except Exception as e:
        # Redis/WebSocket failure should NOT break the main operation
        print("⚠️ WebSocket notification failed")
        print(f"Redis/Channel error: {e}")

    # Always return the database notification
    return notification