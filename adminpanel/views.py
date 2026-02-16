import csv
import html
import os
from decimal import Decimal

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.models import CustomUser
from documents.models import Document, DriveFile
from documents.forms import DocumentUploadForm
from documents.tasks import process_document, sync_drive_folder
from documents.services.vector_store import remove_file_from_vector_store
from chat.models import Conversation, Message
from .models import UsageLog, MasqueradeSession


@staff_member_required
def dashboard(request):
    """Admin dashboard with key stats."""
    total_cost = UsageLog.objects.aggregate(total=Sum("cost"))["total"] or Decimal("0")
    total_input = UsageLog.objects.aggregate(total=Sum("input_tokens"))["total"] or 0
    total_output = UsageLog.objects.aggregate(total=Sum("output_tokens"))["total"] or 0
    context = {
        "total_documents": Document.objects.count(),
        "total_users": CustomUser.objects.count(),
        "total_conversations": Conversation.objects.count(),
        "total_queries": UsageLog.objects.count(),
        "total_cost": total_cost,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "recent_documents": Document.objects.all()[:5],
        "recent_usage": UsageLog.objects.select_related("user").all()[:10],
    }
    return render(request, "adminpanel/dashboard.html", context)


# ─── Documents ───────────────────────────────────────────────────────────────

@staff_member_required
def admin_documents(request):
    qs = Document.objects.all()
    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(domain__icontains=search))
    if status_filter:
        qs = qs.filter(status=status_filter)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "adminpanel/documents.html", {
        "documents": page,
        "search": search,
        "status_filter": status_filter,
        "total": paginator.count,
    })


@staff_member_required
def admin_document_upload(request):
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.uploaded_by = request.user
            doc.save()
            process_document.delay(str(doc.id))
            messages.success(request, f"Document '{doc.title}' uploaded and queued for processing.")
            return redirect("adminpanel:documents")
    else:
        form = DocumentUploadForm()
    return render(request, "adminpanel/document_upload.html", {"form": form})


@staff_member_required
def admin_document_detail(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    return render(request, "adminpanel/document_detail.html", {"document": doc})


@staff_member_required
def admin_document_delete(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        title = doc.title
        if doc.openai_file_id:
            remove_file_from_vector_store(doc.openai_file_id)
        doc.delete()
        messages.success(request, f"Document '{title}' deleted.")
        return redirect("adminpanel:documents")
    return render(request, "adminpanel/document_confirm_delete.html", {"document": doc})


@staff_member_required
@require_POST
def admin_documents_bulk_delete(request):
    """Bulk delete selected documents."""
    ids = request.POST.getlist("selected")
    if ids:
        docs = Document.objects.filter(pk__in=ids)
        count = docs.count()
        for doc in docs:
            if doc.openai_file_id:
                try:
                    remove_file_from_vector_store(doc.openai_file_id)
                except Exception:
                    pass
            doc.delete()
        messages.success(request, f"Deleted {count} document(s).")
    return redirect("adminpanel:documents")


@staff_member_required
def admin_document_reupload(request, pk):
    """Re-upload document to OpenAI Vector Store."""
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        doc.status = "pending"
        doc.save(update_fields=["status"])
        process_document.delay(str(doc.id))
        messages.success(request, f"Re-upload queued for '{doc.title}'.")
    return redirect("adminpanel:document_detail", pk=pk)


# ─── Conversations ───────────────────────────────────────────────────────────

@staff_member_required
def admin_conversations(request):
    qs = Conversation.objects.select_related("user").all()
    search = request.GET.get("q", "").strip()
    user_filter = request.GET.get("user", "").strip()
    if search:
        qs = qs.filter(Q(title__icontains=search))
    if user_filter:
        qs = qs.filter(user__email__icontains=user_filter)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "adminpanel/conversations.html", {
        "conversations": page,
        "search": search,
        "user_filter": user_filter,
        "total": paginator.count,
    })


@staff_member_required
def admin_conversation_detail(request, pk):
    conv = get_object_or_404(Conversation, pk=pk)
    chat_messages = conv.messages.all()
    return render(request, "adminpanel/conversation_detail.html", {"conversation": conv, "chat_messages": chat_messages})


@staff_member_required
@require_POST
def admin_conversation_delete(request, pk):
    """Delete a conversation."""
    conv = get_object_or_404(Conversation, pk=pk)
    conv.delete()
    messages.success(request, "Conversation deleted.")
    return redirect("adminpanel:conversations")


@staff_member_required
@require_POST
def admin_conversations_bulk_delete(request):
    """Bulk delete selected conversations."""
    ids = request.POST.getlist("selected")
    if ids:
        count = Conversation.objects.filter(pk__in=ids).delete()[0]
        messages.success(request, f"Deleted {count} conversation(s).")
    return redirect("adminpanel:conversations")


# ─── Users ───────────────────────────────────────────────────────────────────

@staff_member_required
def admin_users(request):
    qs = CustomUser.objects.all().order_by("-date_joined")
    search = request.GET.get("q", "").strip()
    role_filter = request.GET.get("role", "")
    if search:
        qs = qs.filter(Q(email__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search))
    if role_filter == "staff":
        qs = qs.filter(is_staff=True)
    elif role_filter == "user":
        qs = qs.filter(is_staff=False)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "adminpanel/users.html", {
        "users": page,
        "search": search,
        "role_filter": role_filter,
        "total": paginator.count,
    })


@staff_member_required
def admin_user_edit(request, pk):
    """Edit user details."""
    user = get_object_or_404(CustomUser, pk=pk)
    if request.method == "POST":
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()
        user.is_staff = request.POST.get("is_staff") == "1"
        user.is_active = request.POST.get("is_active") == "1"
        new_password = request.POST.get("new_password", "").strip()
        if new_password:
            user.set_password(new_password)
        user.save()
        messages.success(request, f"User '{user.email}' updated.")
        return redirect("adminpanel:users")
    return render(request, "adminpanel/user_edit.html", {"edit_user": user})


@staff_member_required
@require_POST
def admin_user_delete(request, pk):
    """Delete a user."""
    user = get_object_or_404(CustomUser, pk=pk)
    if user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect("adminpanel:users")
    email = user.email
    user.delete()
    messages.success(request, f"User '{email}' deleted.")
    return redirect("adminpanel:users")


# ─── Masquerade ──────────────────────────────────────────────────────────────

@staff_member_required
def masquerade_start(request, user_id):
    target = get_object_or_404(CustomUser, pk=user_id)
    if request.method == "POST":
        real_user = request.real_user if hasattr(request, "real_user") else request.user
        request.session["masquerade_user_id"] = str(target.id)
        MasqueradeSession.objects.create(admin_user=real_user, target_user=target)
        messages.info(request, f"Now masquerading as {target.email}")
        return redirect("chat:home")
    return render(request, "adminpanel/masquerade_confirm.html", {"target_user": target})


@staff_member_required
def masquerade_stop(request):
    if request.session.get("masquerade_user_id"):
        real_user = request.real_user if hasattr(request, "real_user") else request.user
        session = MasqueradeSession.objects.filter(
            admin_user=real_user, ended_at__isnull=True
        ).order_by("-started_at").first()
        if session:
            session.ended_at = timezone.now()
            session.save(update_fields=["ended_at"])
        del request.session["masquerade_user_id"]
        messages.info(request, "Masquerade ended.")
    return redirect("adminpanel:dashboard")


# ─── Usage Logs ──────────────────────────────────────────────────────────────

@staff_member_required
def admin_usage(request):
    qs = UsageLog.objects.select_related("user").all()
    search = request.GET.get("q", "").strip()
    user_filter = request.GET.get("user", "").strip()
    if search:
        qs = qs.filter(Q(query_text__icontains=search))
    if user_filter:
        qs = qs.filter(user__email__icontains=user_filter)
    totals = qs.aggregate(
        total_cost=Sum("cost"),
        total_input=Sum("input_tokens"),
        total_output=Sum("output_tokens"),
    )
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "adminpanel/usage.html", {
        "logs": page,
        "search": search,
        "user_filter": user_filter,
        "total": paginator.count,
        "total_cost": totals["total_cost"] or Decimal("0"),
        "total_input": totals["total_input"] or 0,
        "total_output": totals["total_output"] or 0,
    })


# ─── Drive ───────────────────────────────────────────────────────────────────

@staff_member_required
def admin_drive_settings(request):
    """Show Drive sync config and synced files."""
    if request.method == "POST":
        folder_id = request.POST.get("folder_id", "").strip()
        sync_interval = request.POST.get("sync_interval", "60").strip()
        messages.info(
            request,
            f"To change settings, update .env: GOOGLE_DRIVE_FOLDER_ID={folder_id}, "
            f"GOOGLE_DRIVE_SYNC_INTERVAL_MINUTES={sync_interval}, then restart services."
        )
        return redirect("adminpanel:drive_settings")

    drive_files = DriveFile.objects.select_related("document").all()
    last_sync = drive_files.order_by("-last_synced").first()
    context = {
        "folder_id": settings.GOOGLE_DRIVE_FOLDER_ID,
        "sync_interval": settings.GOOGLE_DRIVE_SYNC_INTERVAL_MINUTES,
        "service_account_file": settings.GOOGLE_SERVICE_ACCOUNT_FILE,
        "service_account_configured": bool(
            settings.GOOGLE_SERVICE_ACCOUNT_FILE
            and os.path.exists(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
        ),
        "last_sync_time": last_sync.last_synced if last_sync else None,
        "drive_files": drive_files,
        "total_synced": drive_files.count(),
    }
    return render(request, "adminpanel/drive_settings.html", context)


@staff_member_required
def admin_drive_sync(request):
    """Trigger manual Drive sync."""
    if request.method == "POST":
        if not settings.GOOGLE_DRIVE_FOLDER_ID:
            messages.error(request, "Google Drive folder ID is not configured.")
        else:
            sync_drive_folder.delay()
            messages.success(request, "Drive sync has been queued. Check back shortly for results.")
    return redirect("adminpanel:drive_settings")


# ─── Raw Log ─────────────────────────────────────────────────────────────────

@staff_member_required
def admin_raw_log(request):
    """View raw OpenAI response log file."""
    log_path = os.path.join(settings.BASE_DIR, "logs", "raw_responses.log")
    if request.GET.get("clear") == "1":
        if os.path.exists(log_path):
            with open(log_path, "w") as f:
                f.write("")
        return redirect("adminpanel:raw_log")
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "(no log file yet -- ask a question in chat first)"
    content = html.escape(content)
    return HttpResponse(
        f"<html><head><title>Raw Response Log</title>"
        f"<style>body{{font-family:monospace;white-space:pre-wrap;padding:20px;background:#1e1e1e;color:#d4d4d4;font-size:13px;line-height:1.5;}}"
        f"a{{color:#569cd6;margin-right:20px;}}</style></head><body>"
        f"<div style='margin-bottom:20px;'>"
        f"<a href='/panel/raw-log/'>Refresh</a>"
        f"<a href='/panel/raw-log/?clear=1'>Clear Log</a>"
        f"<a href='/panel/'>Back to Admin</a>"
        f"</div>{content}</body></html>",
        content_type="text/html",
    )


# ─── Vector Store Status ─────────────────────────────────────────────────────

@staff_member_required
def admin_vector_store(request):
    """Show OpenAI Vector Store status and file counts."""
    from core.openai_client import get_openai_client
    vs_id = settings.OPENAI_VECTOR_STORE_ID
    vs_data = None
    error = None
    if vs_id:
        try:
            client = get_openai_client()
            vs = client.vector_stores.retrieve(vs_id)
            vs_data = {
                "id": vs.id,
                "name": getattr(vs, "name", ""),
                "status": getattr(vs, "status", ""),
                "file_counts": {
                    "completed": vs.file_counts.completed,
                    "failed": vs.file_counts.failed,
                    "in_progress": vs.file_counts.in_progress,
                    "cancelled": vs.file_counts.cancelled,
                    "total": vs.file_counts.total,
                },
                "usage_bytes": vs.usage_bytes,
                "usage_mb": round(vs.usage_bytes / 1024 / 1024, 1),
                "usage_gb": round(vs.usage_bytes / 1024 / 1024 / 1024, 2),
            }
        except Exception as e:
            error = str(e)
    return render(request, "adminpanel/vector_store.html", {
        "vs_id": vs_id,
        "vs": vs_data,
        "error": error,
    })


# ─── System Settings ─────────────────────────────────────────────────────────

@staff_member_required
def admin_settings(request):
    """View and update system settings."""
    env_path = os.path.join(settings.BASE_DIR, ".env")

    if request.method == "POST":
        # Read current .env
        env_lines = {}
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, val = line.split("=", 1)
                        env_lines[key.strip()] = val.strip()

        # Update settings from form
        model = request.POST.get("chat_model", "").strip()
        if model:
            env_lines["OPENAI_CHAT_MODEL"] = model
        max_results = request.POST.get("max_results", "").strip()
        if max_results:
            env_lines["FILE_SEARCH_MAX_RESULTS"] = max_results
        temperature = request.POST.get("temperature", "").strip()
        if temperature:
            env_lines["CHAT_TEMPERATURE"] = temperature

        # Write back
        with open(env_path, "w") as f:
            for key, val in env_lines.items():
                f.write(f"{key}={val}\n")

        messages.success(request, "Settings saved. Restart services for changes to take effect.")
        return redirect("adminpanel:settings")

    # Read current values
    context = {
        "chat_model": settings.OPENAI_CHAT_MODEL,
        "vector_store_id": settings.OPENAI_VECTOR_STORE_ID,
        "max_results": getattr(settings, "FILE_SEARCH_MAX_RESULTS", 5),
        "temperature": getattr(settings, "CHAT_TEMPERATURE", 0.3),
        "drive_folder_id": settings.GOOGLE_DRIVE_FOLDER_ID,
        "drive_sync_interval": settings.GOOGLE_DRIVE_SYNC_INTERVAL_MINUTES,
    }
    return render(request, "adminpanel/settings.html", context)


# ─── Add User ────────────────────────────────────────────────────────────────

@staff_member_required
def admin_user_add(request):
    """Create a new user."""
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        is_staff = request.POST.get("is_staff") == "1"

        if not email or not password:
            messages.error(request, "Email and password are required.")
            return render(request, "adminpanel/user_add.html", {
                "email": email, "first_name": first_name, "last_name": last_name,
            })

        if CustomUser.objects.filter(email=email).exists():
            messages.error(request, f"User with email '{email}' already exists.")
            return render(request, "adminpanel/user_add.html", {
                "email": email, "first_name": first_name, "last_name": last_name,
            })

        user = CustomUser.objects.create_user(
            email=email, password=password,
            first_name=first_name, last_name=last_name,
            is_staff=is_staff,
        )
        messages.success(request, f"User '{email}' created.")
        return redirect("adminpanel:users")

    return render(request, "adminpanel/user_add.html")


# ─── CSV Export ──────────────────────────────────────────────────────────────

@staff_member_required
def admin_usage_export(request):
    """Export usage logs as CSV."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = "attachment; filename=usage_logs.csv"
    writer = csv.writer(response)
    writer.writerow(["Date", "User", "Query", "Input Tokens", "Output Tokens", "Total Tokens", "Cost ($)"])
    for log in UsageLog.objects.select_related("user").all():
        writer.writerow([
            log.created_at.strftime("%Y-%m-%d %H:%M"),
            log.user.email,
            log.query_text[:200],
            log.input_tokens,
            log.output_tokens,
            log.input_tokens + log.output_tokens,
            f"{log.cost:.6f}",
        ])
    return response
