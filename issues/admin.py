from django.contrib import admin
from .models import Category, Comment, Department, Issue, StatusUpdate


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_email')
    filter_horizontal = ('officials',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'department')


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'category', 'department', 'status', 'reported_by', 'created_at')
    list_filter = ('status', 'category', 'department')
    search_fields = ('title', 'location', 'description')


admin.site.register(StatusUpdate)
admin.site.register(Comment)
