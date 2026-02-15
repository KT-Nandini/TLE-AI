import os

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
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
    context = {
        "total_documents": Document.objects.count(),
        "total_users": CustomUser.objects.count(),
        "total_conversations": Conversation.objects.count(),
        "total_queries": UsageLog.objects.count(),
        "recent_documents": Document.objects.all()[:5],
        "recent_usage": UsageLog.objects.all()[:10],
    }
    return render(request, "adminpanel/dashboard.html", context)


@staff_member_required
def admin_documents(request):
    documents = Document.objects.all()
    return render(request, "adminpanel/documents.html", {"documents": documents})


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
        # Remove from OpenAI Vector Store before deleting locally
        if doc.openai_file_id:
            remove_file_from_vector_store(doc.openai_file_id)
        doc.delete()
        messages.success(request, f"Document '{title}' deleted.")
        return redirect("adminpanel:documents")
    return render(request, "adminpanel/document_confirm_delete.html", {"document": doc})


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


@staff_member_required
def admin_conversations(request):
    conversations = Conversation.objects.select_related("user").all()
    return render(request, "adminpanel/conversations.html", {"conversations": conversations})


@staff_member_required
def admin_conversation_detail(request, pk):
    conv = get_object_or_404(Conversation, pk=pk)
    chat_messages = conv.messages.all()
    return render(request, "adminpanel/conversation_detail.html", {"conversation": conv, "chat_messages": chat_messages})


@staff_member_required
def admin_users(request):
    users = CustomUser.objects.all().order_by("-date_joined")
    return render(request, "adminpanel/users.html", {"users": users})


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
        # End the session audit trail
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


@staff_member_required
def admin_usage(request):
    logs = UsageLog.objects.select_related("user").all()[:100]
    return render(request, "adminpanel/usage.html", {"logs": logs})


@staff_member_required
def admin_drive_settings(request):
    """Show Drive sync config and synced files."""
    if request.method == "POST":
        folder_id = request.POST.get("folder_id", "").strip()
        sync_interval = request.POST.get("sync_interval", "60").strip()
        # Note: These are env-based settings. We show them but updating
        # requires changing .env and restarting. Show a message.
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
            and __import__("os").path.exists(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
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
    # Escape HTML in log content
    import html
    content = html.escape(content)
    return HttpResponse(
        f"<html><head><title>Raw Response Log</title>"
        f"<style>body{{font-family:monospace;white-space:pre-wrap;padding:20px;background:#1e1e1e;color:#d4d4d4;font-size:13px;line-height:1.5;}}"
        f"a{{color:#569cd6;margin-right:20px;}}</style></head><body>"
        f"<div style='margin-bottom:20px;'>"
        f"<a href='/admin-panel/raw-log/'>Refresh</a>"
        f"<a href='/admin-panel/raw-log/?clear=1'>Clear Log</a>"
        f"<a href='/admin-panel/'>Back to Admin</a>"
        f"</div>{content}</body></html>",
        content_type="text/html",
    )
