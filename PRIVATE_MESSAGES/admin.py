# Models intentionally not registered; operators must not view encrypted envelopes or key material.
#
# If any pm_* model is accidentally picked up by auto-discovery (e.g. via a
# third-party admin package), unregister it explicitly below.
#
# from django.contrib import admin
# from .models import IdentityKey, SignedPreKey, OneTimePreKey, EncryptedEnvelope, PrivateSession
# for model in [IdentityKey, SignedPreKey, OneTimePreKey, EncryptedEnvelope, PrivateSession]:
#     try:
#         admin.site.unregister(model)
#     except admin.sites.NotRegistered:
#         pass
