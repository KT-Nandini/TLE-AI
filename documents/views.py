from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import Document
from .forms import DocumentUploadForm
from .tasks import process_document
from .services.vector_store import remove_file_from_vector_store


@staff_member_required
def document_list(request):
    docs = Document.objects.all()
    return render(request, "documents/list.html", {"documents": docs})


@staff_member_required
def document_upload(request):
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.uploaded_by = request.user
            doc.save()
            process_document.delay(str(doc.id))
            messages.success(request, f"Document '{doc.title}' uploaded and queued for processing.")
            return redirect("documents:list")
    else:
        form = DocumentUploadForm()
    return render(request, "documents/upload.html", {"form": form})


@staff_member_required
def document_detail(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    return render(request, "documents/detail.html", {"document": doc})


@staff_member_required
def document_delete(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        title = doc.title
        # Remove from OpenAI Vector Store before deleting locally
        if doc.openai_file_id:
            remove_file_from_vector_store(doc.openai_file_id)
        doc.delete()
        messages.success(request, f"Document '{title}' deleted.")
        return redirect("documents:list")
    return render(request, "documents/confirm_delete.html", {"document": doc})


@staff_member_required
def document_reupload(request, pk):
    """Re-upload document to OpenAI Vector Store."""
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        doc.status = "pending"
        doc.save(update_fields=["status"])
        process_document.delay(str(doc.id))
        messages.success(request, f"Re-upload queued for '{doc.title}'.")
    return redirect("documents:detail", pk=pk)

