from datetime import timedelta
from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    contact_email = models.EmailField()
    officials = models.ManyToManyField(User, blank=True, related_name='departments')

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='categories'
    )
    sla_hours = models.PositiveIntegerField(default=72, help_text='Target resolution window in hours')
    severity_weight = models.PositiveIntegerField(default=2, help_text='Base urgency multiplier (1-5)')

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Issue(models.Model):
    STATUS_CHOICES = [
        ('reported', 'Reported'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=255)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    photo = models.ImageField(upload_to='issue_photos/', blank=True, null=True)
    resolution_photo = models.ImageField(upload_to='resolution_photos/', blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='issues')
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='issues'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='reported')
    reported_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reported_issues')
    upvotes = models.ManyToManyField(User, blank=True, related_name='upvoted_issues')
    citizen_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.department and self.category and self.category.department:
            self.department = self.category.department
        if not self.due_at and self.category:
            base_time = self.created_at or timezone.now()
            self.due_at = base_time + timedelta(hours=self.category.sla_hours)
        if self.status == 'resolved' and not self.resolved_at:
            self.resolved_at = timezone.now()
        elif self.status != 'resolved':
            self.resolved_at = None
            self.citizen_verified = False
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('issue_detail', kwargs={'pk': self.pk})

    @property
    def days_open(self):
        end = self.resolved_at or timezone.now()
        return max(0, (end - self.created_at).days)

    @property
    def is_overdue(self):
        return bool(self.status != 'resolved' and self.due_at and timezone.now() > self.due_at)

    @property
    def upvote_count(self):
        return self.upvotes.count()

    @property
    def priority_score(self):
        if self.status == 'resolved':
            return 0
        weight = self.category.severity_weight if self.category else 2
        score = (weight * 10) + (self.upvotes.count() * 5)
        if self.is_overdue:
            score += 35
        return score

    @property
    def priority_level(self):
        s = self.priority_score
        if s >= 50:
            return 'critical'
        if s >= 25:
            return 'high'
        return 'normal'

    def __str__(self):
        return f"#{self.pk} {self.title}"


class StatusUpdate(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='updates')
    old_status = models.CharField(max_length=20, choices=Issue.STATUS_CHOICES)
    new_status = models.CharField(max_length=20, choices=Issue.STATUS_CHOICES)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    remarks = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']


class Comment(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    text = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, null=True, blank=True)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
