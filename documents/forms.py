from django import forms
from .models import Document


class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "file", "authority_level", "domain"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full border rounded px-3 py-2", "placeholder": "Document title"}),
            "file": forms.ClearableFileInput(attrs={"class": "w-full border rounded px-3 py-2", "accept": ".pdf,.docx,.txt"}),
            "authority_level": forms.Select(attrs={"class": "w-full border rounded px-3 py-2"}),
            "domain": forms.Select(attrs={"class": "w-full border rounded px-3 py-2"}),
        }

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if f:
            ext = f.name.rsplit(".", 1)[-1].lower()
            if ext not in ("pdf", "docx", "txt"):
                raise forms.ValidationError("Only PDF, DOCX, and TXT files are supported.")
        return f
