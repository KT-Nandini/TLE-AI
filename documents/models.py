import uuid
from django.conf import settings
from django.db import models


class Document(models.Model):
    AUTHORITY_CHOICES = [
        ("statute", "Statute"),
        ("rule", "Rule"),
        ("case", "Case"),
        ("practice_guide", "Practice Guide"),
    ]
    DOMAIN_CHOICES = [
        ("family", "Family"),
        ("criminal", "Criminal"),
        ("civil", "Civil"),
        ("property", "Property"),
        ("probate", "Probate"),
        ("business", "Business"),
        ("employment", "Employment"),
        ("immigration", "Immigration"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500)
    file = models.FileField(upload_to="documents/", max_length=500)
    authority_level = models.CharField(max_length=20, choices=AUTHORITY_CHOICES)
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    jurisdiction = models.CharField(max_length=10, default="TX")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    openai_file_id = models.CharField(max_length=100, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uploaded_documents"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class DriveFile(models.Model):
    drive_file_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=100)
    md5_checksum = models.CharField(max_length=64, blank=True, default="")
    modified_time = models.DateTimeField()
    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, null=True, related_name="drive_file"
    )
    last_synced = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_synced"]

    def __str__(self):
        return self.name
