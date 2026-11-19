from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from issues.models import Department, Category, Issue, StatusUpdate, Comment


class Command(BaseCommand):
    help = 'Populate CivicPulse with sample departments, categories, users, and geo-tagged issues'

    def handle(self, *args, **kwargs):
        admin, _ = User.objects.get_or_create(username='admin', defaults={'email': 'admin@civicpulse.local', 'is_staff': True, 'is_superuser': True})
        admin.set_password('admin123')
        admin.save()

        official, _ = User.objects.get_or_create(username='official_roads', defaults={'first_name': 'Ramesh', 'email': 'roads@civicpulse.local'})
        official.set_password('pass1234')
        official.save()

        citizen, _ = User.objects.get_or_create(username='citizen_ananya', defaults={'first_name': 'Ananya', 'email': 'ananya@example.com'})
        citizen.set_password('pass1234')
        citizen.save()

        roads, _ = Department.objects.get_or_create(name='Roads & Infrastructure', defaults={'contact_email': 'roads@city.gov'})
        roads.officials.add(official)

        sanitation, _ = Department.objects.get_or_create(name='Sanitation & Waste', defaults={'contact_email': 'sanitation@city.gov'})
        electrical, _ = Department.objects.get_or_create(name='Street Lighting & Power', defaults={'contact_email': 'power@city.gov'})
        water, _ = Department.objects.get_or_create(name='Water Supply & Drainage', defaults={'contact_email': 'water@city.gov'})

        cat_pothole, _ = Category.objects.get_or_create(name='Pothole', defaults={'department': roads, 'sla_hours': 96})
        cat_garbage, _ = Category.objects.get_or_create(name='Garbage Overflow', defaults={'department': sanitation, 'sla_hours': 24})
        cat_light, _ = Category.objects.get_or_create(name='Broken Streetlight', defaults={'department': electrical, 'sla_hours': 48})
        cat_water, _ = Category.objects.get_or_create(name='Water Leakage', defaults={'department': water, 'sla_hours': 12})

        Issue.objects.all().delete()

        i1 = Issue.objects.create(
            title='Deep pothole near Sector 14 Metro Gate 2',
            description='Large crater in the left lane causing traffic bottlenecks and two-wheeler skids during evening rush.',
            location='Sector 14 Main Road, near Gate 2',
            latitude=28.6692,
            longitude=77.4538,
            category=cat_pothole,
            status='in_progress',
            reported_by=citizen,
        )
        i1.upvotes.add(citizen, official, admin)
        StatusUpdate.objects.create(
            issue=i1, old_status='reported', new_status='in_progress',
            updated_by=official, remarks='Inspection team dispatched; cold-mix patching scheduled tonight.'
        )
        Comment.objects.create(issue=i1, user=citizen, text='Thank you! Safety cones have been placed around the spot.')

        i2 = Issue.objects.create(
            title='Overflowing garbage bin outside Central Park',
            description='Community bin has not been cleared for 3 days; waste spilling onto the footpath.',
            location='Central Park North Gate, Block C',
            latitude=28.6745,
            longitude=77.4412,
            category=cat_garbage,
            status='reported',
            reported_by=citizen,
        )
        # Force SLA overdue for demo visibility
        Issue.objects.filter(pk=i2.pk).update(
            created_at=timezone.now() - timedelta(hours=36),
            due_at=timezone.now() - timedelta(hours=12),
        )
        i2.upvotes.add(citizen, admin)

        i3 = Issue.objects.create(
            title='Three consecutive streetlights out on Link Road',
            description='Stretch between Cross 4 and Cross 6 is completely dark after 7 PM.',
            location='Link Road, Cross 4 to 6',
            latitude=28.6621,
            longitude=77.4605,
            category=cat_light,
            status='resolved',
            citizen_verified=True,
            reported_by=citizen,
        )
        i3.upvotes.add(citizen)
        StatusUpdate.objects.create(
            issue=i3, old_status='reported', new_status='resolved',
            updated_by=admin, remarks='Replaced faulty LED drivers and restored power.'
        )

        i4 = Issue.objects.create(
            title='Burst water pipeline flooding service lane',
            description='Clean water leaking continuously from an underground joint near the transformer.',
            location='Indirapuram Habitat Service Lane',
            latitude=28.6418,
            longitude=77.3714,
            category=cat_water,
            status='reported',
            reported_by=citizen,
        )
        i4.upvotes.add(citizen, official)

        self.stdout.write(self.style.SUCCESS('Upgraded & seeded CivicPulse!'))
