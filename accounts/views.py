from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect


@login_required
def profile_view(request):
    return render(request, "account/profile.html")


@login_required
def login_redirect_view(request):
    """Redirect admin users to panel, normal users to chat."""
    if request.user.is_staff:
        return redirect("/panel/")
    return redirect("/chat/")
