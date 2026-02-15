"""Masquerade middleware — allows admins to view the site as another user."""
from django.utils import timezone


class MasqueradeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.is_masquerading = False
        request.real_user = request.user

        if request.user.is_authenticated and request.session.get("masquerade_user_id"):
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
