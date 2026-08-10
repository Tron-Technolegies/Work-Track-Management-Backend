from channels.generic.websocket import AsyncWebsocketConsumer
import json

class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
            
            self.user = self.scope.get("user")

            print("Connected User:", self.user)

            # Reject anonymous users
            if not self.user or self.user.is_anonymous:
                print("Anonymous user. Closing connection...")
                await self.close()
                return

            self.group_name = f"user_{self.user.id}"

            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )

            print(f"Joined Group: {self.group_name}")

            await self.accept()

            print("✅ WebSocket Connected")


    async def disconnect(self, close_code):
        print("Disconnected:", close_code)

        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def send_notification(self, event):
        print("📩 Consumer received event:", event)
        await self.send(
            text_data=json.dumps({
                "id": event["id"],
                "title": event["title"],
                "message": event["message"],
                "notification_type": event["notification_type"],
                "created_at": event["created_at"],
            })
        )
        print("✅ Sent notification to WebSocket")
