# accounts/forms.py
from django import forms

class LoginForm(forms.Form):
    username = forms.CharField(
        label="User ID",
        max_length=150,
        widget=forms.TextInput(attrs={
            "placeholder": "Masukkan ID Anda",
            "class": "form-control"
        })
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "placeholder": "Masukkan Password",
            "class": "form-control"
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        password = cleaned_data.get("password")

        if not username or not password:
            raise forms.ValidationError("⚠️ Harap isi username dan password")

        return cleaned_data
