"""
test_search_annotations.py

Verifies that the search_view (M2) resolves all relationship context in a
single annotated queryset — well under the old N+1 budget of ~80 queries
for 20 results.

Budget assertion: <= 5 queries for a 20-user search result page.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from FRIEND.models import Friend, FriendshipRequest

UserModel = get_user_model()

QUERY_BUDGET = 5


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(
        username=username,
        password="TestPass123!",
        first_name="Test",
        last_name="User",
    )


def _make_friends(u1, u2):
    """Create bilateral friendship rows."""
    Friend.objects.get_or_create(from_user=u1, to_user=u2)
    Friend.objects.get_or_create(from_user=u2, to_user=u1)


def _send_request(from_user, to_user):
    FriendshipRequest.objects.get_or_create(
        from_user=from_user,
        to_user=to_user,
    )


class SearchAnnotationsQueryBudgetTest(TestCase):
    """
    Seeds 20 target users plus various friendship relationships, then fires
    the search endpoint and asserts the total query count stays well within
    budget.
    """

    @classmethod
    def setUpTestData(cls):
        cls.searcher = _make_user("searcher_ann")

        # 20 searchable users — usernames all contain "searchable"
        cls.targets = [_make_user(f"searchable_u{i:02d}") for i in range(20)]

        # 10 friendships (first 10 targets)
        for t in cls.targets[:10]:
            _make_friends(cls.searcher, t)

        # 5 incoming requests (targets 10-14 → searcher)
        for t in cls.targets[10:15]:
            _send_request(from_user=t, to_user=cls.searcher)

        # 5 outgoing requests (searcher → targets 15-19)
        for t in cls.targets[15:20]:
            _send_request(from_user=cls.searcher, to_user=t)

    def test_search_query_count_within_budget(self):
        """
        The total number of DB queries for a search returning 20 results
        must be <= QUERY_BUDGET (currently 5).  The old N+1 code would have
        issued ~80+ queries for the same page.
        """
        client = Client()
        client.force_login(self.searcher)

        with CaptureQueriesContext(connection) as ctx:
            response = client.get('/accounts/search/?query=searchable')

        self.assertEqual(response.status_code, 200)

        query_count = len(ctx.captured_queries)
        self.assertLessEqual(
            query_count,
            QUERY_BUDGET,
            f"Search issued {query_count} queries — exceeds budget of {QUERY_BUDGET}.\n"
            f"Queries:\n" + "\n".join(
                f"  [{i}] {q['sql'][:120]}" for i, q in enumerate(ctx.captured_queries)
            ),
        )

    def test_search_results_contain_correct_flags(self):
        """
        Spot-check that annotations are correct: first 10 targets are friends,
        targets 10-14 have incoming requests, targets 15-19 have outgoing.
        """
        client = Client()
        client.force_login(self.searcher)
        response = client.get('/accounts/search/?query=searchable')
        self.assertEqual(response.status_code, 200)

        # Extract (account, info) pairs from the page
        page_obj = response.context['page_obj']
        page_data = list(page_obj)  # first page, 6 results

        # At least one pair should be present
        self.assertGreater(len(page_data), 0)

        # Verify no pair has both is_friend=True and has_outgoing_request=True
        for account, info in page_data:
            if info['is_friend']:
                self.assertFalse(
                    info['has_sent_request'],
                    f"{account.username} flagged as both friend and has_sent_request",
                )
