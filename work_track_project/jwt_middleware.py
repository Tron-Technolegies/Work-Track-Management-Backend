from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model

User = get_user_model()

class JWTAuthMiddleware:    
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):

        query_string = scope["query_string"].decode()

        query_params = parse_qs(query_string)

        token = query_params.get("token", [None])[0]

        if token:
            user = await get_user(token)

            if user:
                scope["user"] = user

        print("JWT Token:", token)

        return await self.inner(scope, receive, send)
    
     # def __init__(self, inner):
    #     self.inner = inner

    # async def __call__(self, scope, receive, send):  #This method runs every time a WebSocket connection is made. It's similar to how a Django view runs for every HTTP request.
    #     return await self.inner(scope, receive, send)  #Later, before this line, we'll:Read the JWT token.Validate it.Find the user.Store it in:


@database_sync_to_async
def get_user(token):
    try:
        # Validate JWT token
        access_token = AccessToken(token)

        # Extract user_id from the token
        user_id = access_token["user_id"]

        # Get the user from the database
        return User.objects.get(id=user_id)

    except User.DoesNotExist:
        return None

    except Exception:
        return None
    