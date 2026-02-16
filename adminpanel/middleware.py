"""Masquerade middleware — allows admins to view the site as another user."""
from django.utils import timezone


class MasqueradeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.is_masquerading = False
        request.real_user = request.user

        # Skip masquerading for the stop URL so admin can always access it
        if request.user.is_authenticated and request.session.get("masquerade_user_id"):
            if request.path.rstrip("/").endswith("masquerade/stop"):
                del request.session["masquerade_user_id"]
                request.is_masquerading = False
            else:
                from accounts.models import CustomUser
                try:
                    target = CustomUser.objects.get(id=request.session["masquerade_user_id"])
                    request.real_user = request.user
                    request.user = target
                    request.is_masquerading = True
                except CustomUser.DoesNotExist:
                    del request.session["masquerade_user_id"]

        response = self.get_response(request)
        return response
