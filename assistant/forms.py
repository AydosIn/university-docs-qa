from django import forms


class AskForm(forms.Form):
    text = forms.CharField(max_length=500, strip=True)
