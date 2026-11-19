from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Issue, Comment


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=60, required=False)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'email']


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ['title', 'category', 'location', 'latitude', 'longitude', 'description', 'photo']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'location': forms.TextInput(attrs={'placeholder': 'Street name, landmark, or click on the map below'}),
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
        }

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo and photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Image file must be under 5 MB.')
        return photo


class StatusUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=Issue.STATUS_CHOICES)
    resolution_photo = forms.ImageField(
        required=False,
        label='Resolution proof photo (Before/After)',
        help_text='Attach a photo showing the completed repair when marking as Resolved.',
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Note visible on the public audit timeline'}),
    )


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['text']
        labels = {'text': 'Add a comment'}
        widgets = {'text': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Write a follow-up or note...'})}
