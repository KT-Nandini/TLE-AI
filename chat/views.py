import json
import logging
from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from .models import Conversation, Message, ConversationSummary
from .services.assistant import stream_response as assistant_stream_response
from .tasks import summarize_conversation, generate_conversation_title
from adminpanel.models import UsageLog

logger = logging.getLogger(__name__)


@login_required
def chat_home(request):
    """Main chat page — redirect to most recent conversation or show empty state."""
    conversations = Conversation.objects.filter(user=request.user, is_archived=False).order_by("-is_pinned", "-updated_at")
    latest = conversations.first()
    if latest:
        return redirect("chat:detail", pk=latest.pk)
    return render(request, "chat/home.html", {"conversations": conversations})


@login_required
def conversation_new(request):
    """Create a new conversation and redirect to it."""
    conv = Conversation.objects.create(user=request.user)
    if request.headers.get("HX-Request"):
        return redirect("chat:detail", pk=conv.pk)
    return redirect("chat:detail", pk=conv.pk)


@login_required
def conversation_detail(request, pk):
    """Display a conversation with its messages."""
    conv = get_object_or_404(Conversation, pk=pk, user=request.user)
    chat_messages = conv.messages.all()
    conversations = Conversation.objects.filter(user=request.user, is_archived=False).order_by("-is_pinned", "-updated_at")
    return render(request, "chat/detail.html", {
        "conversation": conv,
        "chat_messages": chat_messages,
        "conversations": conversations,
    })


@login_required
@require_POST
def send_message(request, pk):
    """Save user message and trigger streaming response via HTMX."""
    conv = get_object_or_404(Conversation, pk=pk, user=request.user)
    content = request.POST.get("message", "").strip()
    if not content:
        return JsonResponse({"error": "Empty message"}, status=400)

    # Save user message
    user_msg = Message.objects.create(conversation=conv, role="user", content=content)

    # Return HTML for the user message, with SSE trigger for assistant response
    return render(request, "chat/partials/user_message.html", {
        "message": user_msg,
        "conversation": conv,
    })


@login_required
def stream_response(request, pk):
    """SSE endpoint: stream response via OpenAI Responses API with file_search."""
    conv = get_object_or_404(Conversation, pk=pk, user=request.user)

    # Get the latest user message
    last_user_msg = conv.messages.filter(role="user").order_by("-created_at").first()
    if not last_user_msg:
        return StreamingHttpResponse("data: [DONE]\n\n", content_type="text/event-stream")

    def event_stream():
        try:
            # Step 1: Build conversation history — token limit first, max 10 messages
            MAX_HISTORY_CHARS = 16000  # ~4000 tokens (1 token ≈ 4 chars)
            MAX_MESSAGES = 10
            all_messages = list(conv.messages.order_by("-created_at"))  # newest first
            history = []
            total_chars = 0
            for msg in all_messages:
                if len(history) >= MAX_MESSAGES:
                    break
                msg_chars = len(msg.content)
                if total_chars + msg_chars > MAX_HISTORY_CHARS and history:
                    break  # already have at least 1 message, stop adding
                history.insert(0, {"role": msg.role, "content": msg.content})
                total_chars += msg_chars

            # Step 2: Get latest summary if exists
            summary = ""
            latest_summary = conv.summaries.first()
            if latest_summary:
                summary = latest_summary.summary_text

            # Step 3: Stream response via Responses API
            full_response = ""
            citations = []
            usage_data = {"input_tokens": 0, "output_tokens": 0}
            for chunk in assistant_stream_response(history, summary):
                if "token" in chunk:
                    full_response += chunk["token"]
                    data = json.dumps({"token": chunk["token"]})
                    yield f"data: {data}\n\n"
                elif "citations" in chunk:
                    citations = chunk["citations"]
                elif "usage" in chunk:
                    usage_data = chunk["usage"]

            # Step 4: Save assistant message
            Message.objects.create(
                conversation=conv,
                role="assistant",
                content=full_response,
                citations=citations,
            )

            # Step 5: Log usage with token counts and cost
            in_tokens = usage_data.get("input_tokens", 0)
            out_tokens = usage_data.get("output_tokens", 0)
            # gpt-4o-mini: $0.15/1M input, $0.60/1M output
            cost = (in_tokens * 0.15 / 1_000_000) + (out_tokens * 0.60 / 1_000_000)
            UsageLog.objects.create(
                user=conv.user,
                conversation=conv,
                query_text=last_user_msg.content,
                domain_classified="",
                chunks_retrieved=0,
                response_tokens=len(full_response.split()),
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cost=cost,
            )

            # Step 6: Send citations to frontend
            if citations:
                yield f"data: {json.dumps({'citations': citations})}\n\n"

            # Step 7: Background tasks
            msg_count = conv.messages.count()
            if msg_count == 2:
                generate_conversation_title.delay(str(conv.id))
            # Summarize when history was trimmed by token limit or after 10+ messages
            if msg_count >= 10 or (msg_count >= 6 and total_chars >= MAX_HISTORY_CHARS):
                summarize_conversation.delay(str(conv.id))

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.exception("Error in stream_response")
            error_data = json.dumps({"error": str(e)})
            yield f"data: {error_data}\n\n"
            yield "data: [DONE]\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
@require_POST
def conversation_archive(request, pk):
    """Archive a conversation."""
    conv = get_object_or_404(Conversation, pk=pk, user=request.user)
    conv.is_archived = True
    conv.save(update_fields=["is_archived"])
    return redirect("chat:home")


@login_required
@require_POST
def conversation_rename(request, pk):
    """Rename a conversation via AJAX."""
    conv = get_object_or_404(Conversation, pk=pk, user=request.user)
    title = request.POST.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title cannot be empty"}, status=400)
    conv.title = title[:200]
    conv.save(update_fields=["title"])
    return JsonResponse({"ok": True, "title": conv.title})


@login_required
@require_POST
def conversation_pin(request, pk):
    """Toggle pin status of a conversation."""
    conv = get_object_or_404(Conversation, pk=pk, user=request.user)
    conv.is_pinned = not conv.is_pinned
    conv.save(update_fields=["is_pinned"])
    return JsonResponse({"ok": True, "is_pinned": conv.is_pinned})


@login_required
def conversation_sidebar(request):
    """HTMX partial: return updated conversation sidebar."""
    conversations = Conversation.objects.filter(user=request.user, is_archived=False).order_by("-is_pinned", "-updated_at")
    return render(request, "chat/partials/sidebar.html", {"conversations": conversations})


@login_required
def conversation_title(request, pk):
    """Return the current title of a conversation as JSON."""
    conv = get_object_or_404(Conversation, pk=pk, user=request.user)
    return JsonResponse({"title": conv.title})
