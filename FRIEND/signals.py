from django.dispatch import Signal

friendship_request_created = Signal()
friendship_request_rejected = Signal()
friendship_request_canceled = Signal()
friendship_request_viewed = Signal()
friendship_request_accepted = Signal()
friendship_removed = Signal()