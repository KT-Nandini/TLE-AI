"""Celery tasks for chat — background summarization and title generation."""
import logging
from decimal import Decimal
from celery import shared_task

logger = logging.getLogger(__name__)

# gpt-4o-mini pricing
_INPUT_PRICE = Decimal("0.15")   # per 1M tokens
_OUTPUT_PRICE = Decimal("0.60")  # per 1M tokens
_MILLION = Decimal("1000000")


def _log_usage(user, conversation, query_text, input_tokens, output_tokens):
    """Save a UsageLog entry for a background API call."""
    from adminpanel.models import UsageLog
    cost = (Decimal(input_tokens) * _INPUT_PRICE / _MILLION) + (Decimal(output_tokens) * _OUTPUT_PRICE / _MILLION)
    UsageLog.objects.create(
        user=user,
        conversation=conversation,
        query_text=query_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
    )


@shared_task
def summarize_conversation(conversation_id: str):
    """Create a summary of older messages when conversation exceeds 20 messages."""
    from chat.models import Conversation, ConversationSummary
    from core.openai_client import get_openai_client
    from django.conf import settings

    conversation = Conversation.objects.get(id=conversation_id)
    messages = list(conversation.messages.order_by("created_at"))

    if len(messages) <= 20:
        return

    # Summarize all but the last 10 messages
    older_messages = messages[:-10]
    formatted = "\n".join(
        f"{m.role.upper()}: {m.content[:500]}" for m in older_messages
    )

    client = get_openai_client()
    response = client.chat.completions.create(
        model=settings.OPENAI_CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Summarize this legal conversation concisely. "
                    "Focus on: what topics were discussed, what legal questions were asked, "
                    "what sources/statutes were referenced, and what conclusions were reached. "
                    "Do NOT add new legal information. Keep it factual and brief."
                ),
            },
            {"role": "user", "content": formatted},
        ],
        max_tokens=500,
        temperature=0.1,
    )
    summary_text = response.choices[0].message.content.strip()

    usage = response.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0

    ConversationSummary.objects.create(
        conversation=conversation,
        summary_text=summary_text,
        messages_covered_until=older_messages[-1].created_at,
    )

    _log_usage(conversation.user, conversation, "[summarize_conversation]", in_tok, out_tok)
    logger.info(f"Summarized {len(older_messages)} messages for conversation {conversation_id} (in={in_tok}, out={out_tok})")


@shared_task
def generate_conversation_title(conversation_id: str):
    """Auto-generate a title after the first exchange."""
    from chat.models import Conversation
    from chat.services.llm import generate_title

    conversation = Conversation.objects.get(id=conversation_id)
    messages = list(conversation.messages.order_by("created_at")[:2])

    if len(messages) < 2:
        return

    user_msg = messages[0].content if messages[0].role == "user" else messages[1].content
    asst_msg = messages[1].content if messages[1].role == "assistant" else messages[0].content

    result = generate_title(user_msg, asst_msg)
    title = result["title"]
    conversation.title = title[:200]
    conversation.save(update_fields=["title"])

    _log_usage(conversation.user, conversation, "[generate_title]", result["input_tokens"], result["output_tokens"])
    logger.info(f"Generated title for conversation {conversation_id}: {title} (in={result['input_tokens']}, out={result['output_tokens']})")
