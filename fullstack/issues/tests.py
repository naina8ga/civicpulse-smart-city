from datetime import timedelta
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Category, Department, Issue


class CivicPulseUltraCapstoneTests(TestCase):
    def setUp(self):
        self.citizen = User.objects.create_user('test_citizen', 'c@test.com', 'pass1234')
        self.official = User.objects.create_user('test_official', 'o@test.com', 'pass1234')
        self.dept = Department.objects.create(name='Roads & Bridges', contact_email='roads@city.gov')
        self.dept.officials.add(self.official)
        self.cat = Category.objects.create(
            name='Pothole', department=self.dept, sla_hours=24, severity_weight=4
        )
        self.issue = Issue.objects.create(
            title='Deep pothole near main metro gate',
            description='Causing traffic congestion and two-wheeler accidents.',
            location='Main Metro Gate, Sector 18',
            category=self.cat,
            reported_by=self.citizen,
            latitude=28.6692,
            longitude=77.4538,
        )

    def test_auto_routing_and_sla_deadline(self):
        self.assertEqual(self.issue.department, self.dept)
        self.assertIsNotNone(self.issue.due_at)
        self.assertFalse(self.issue.is_overdue)

    def test_sla_breach_detection(self):
        self.issue.due_at = timezone.now() - timedelta(hours=2)
        self.issue.save()
        self.assertTrue(self.issue.is_overdue)
        self.assertEqual(self.issue.priority_level, 'critical')

    def test_priority_score_increases_with_upvotes(self):
        base_score = self.issue.priority_score
        self.issue.upvotes.add(self.citizen)
        self.assertGreater(self.issue.priority_score, base_score)

    def test_ai_smart_classify_endpoint(self):
        client = Client()
        res = client.get(reverse('smart_classify'), {'text': 'Huge asphalt pothole on highway'})
        data = res.json()
        self.assertTrue(data['matched'])
        self.assertEqual(data['category_name'], 'Pothole')

    def test_duplicate_detection_endpoint(self):
        client = Client()
        res = client.get(reverse('check_duplicates'), {'q': 'pothole metro gate'})
        self.assertEqual(len(res.json()['matches']), 1)

    def test_civicbot_nlp_endpoint(self):
        client = Client()
        res = client.get(reverse('civicbot_api'), {'q': 'top priority'})
        self.assertIn('Deep pothole', res.json()['reply'])

    def test_public_rest_api(self):
        client = Client()
        res = client.get(reverse('public_issues_api'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['count'], 1)

    def test_budget_simulator_and_executive_brief(self):
        client = Client()
        self.assertEqual(client.get(reverse('budget_simulator')).status_code, 200)
        self.assertEqual(client.get(reverse('executive_brief')).status_code, 200)

    def test_command_center_and_pulse_api(self):
        client = Client()
        self.assertEqual(client.get(reverse('command_center')).status_code, 200)
        self.assertEqual(client.get(reverse('command_pulse_api')).json()['total'], 1)

    def test_rbac_blocks_citizen_from_dashboard(self):
        client = Client()
        client.force_login(self.citizen)
        res = client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 403)

    def test_official_can_access_dashboard_and_kanban(self):
        client = Client()
        client.force_login(self.official)
        self.assertEqual(client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(client.get(reverse('kanban_board')).status_code, 200)
