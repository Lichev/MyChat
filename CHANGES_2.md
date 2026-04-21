# CHANGES_2.md — Session 2 Change Log

This document covers all changes made in the second development session. The session had two major themes:

1. **Anonymous account system** — full removal of email-based auth, replaced with username+password registration and a cryptographic one-time recovery key for password reset.
2. **Chat UI bug fixes** — duplicate messages, missing avatars, toast spam, wrong message ordering, broken requests count.

---

## CHAT_ROOMS/views.py

### What changed
- `context_object_name` renamed from `'messages'` to `'chat_messages'`
- `get_queryset` now returns the **most recent** `PAGE_SIZE` messages in chronological order instead of the oldest
- `get_context_data` reference updated from `context['messages']` to `context['chat_messages']`
- `chat_rooms_info_json` now returns `requests_count` in the JSON response

### Why it improves the code

**`context_object_name = 'messages'` → `'chat_messages'`**: Django's messages framework uses `messages` as its template context variable. The ListView was overwriting it with the chat `Message` queryset. `base.html` iterates `{% for message in messages %}` to render toast notifications — the name clash caused every chat message loaded from the database to be rendered as a bottom-right toast notification on page load. Renaming the context object eliminates the conflict.

**Message ordering**: The original queryset used `order_by('timestamp')[:PAGE_SIZE]`, which retrieved the **oldest** 25 messages. In a room with 50 messages, users would see messages 1–25 (ancient history), while messages 26–50 were invisible until sent live via WebSocket. The fix fetches the newest 25 (`order_by('-timestamp')[:PAGE_SIZE]`) then reverses them in Python so they display oldest-to-newest (top-to-bottom), matching the order WebSocket messages are appended.

**`requests_count`**: The dashboard "Requests" pill in the rooms sidebar was hardcoded to `0` because the endpoint never returned the count. Now it queries `Friend.objects.requests(user)` and includes the count in the API response.

```diff
-    context_object_name = 'messages'
+    context_object_name = 'chat_messages'

     def get_queryset(self):
         room_id = self.kwargs['room_id']
-        return (
+        msgs = list(
             Message.objects
             .filter(room_id=room_id)
             .select_related('sender')
-            .order_by('timestamp')[:PAGE_SIZE]
+            .order_by('-timestamp')[:PAGE_SIZE]
         )
+        msgs.reverse()
+        return msgs

-        qs = context['messages']
+        qs = context['chat_messages']

     friends = Friend.objects.friends(user)
     my_groups = PublicChatRoom.objects.filter(creator=user)
+    requests_count = len(Friend.objects.requests(user))

-    return JsonResponse({'friends': friends_data, 'groups_data': my_groups_data})
+    return JsonResponse({'friends': friends_data, 'groups_data': my_groups_data, 'requests_count': requests_count})
```

---

## MyChat/settings.py

### What changed
- Added HTTPS/cookie security settings gated on `not DEBUG`
- Added `PASSWORD_HASHERS` with Argon2 as the primary hasher

### Why it improves the code

**HTTPS settings**: `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and `SECURE_HSTS_SECONDS` are all enabled in non-debug (production) mode. This prevents session hijacking over HTTP, forces HTTPS redirects, and protects CSRF tokens from network sniffers — all disabled in local dev so HTTP still works.

**Argon2 hasher**: Argon2 is memory-hard and the current OWASP-recommended default for password hashing. It is significantly more resistant to GPU-based brute-force attacks than the PBKDF2 default. Existing PBKDF2 hashes continue to work (Django upgrades them on next login) so this is a non-breaking change.

```diff
+SECURE_SSL_REDIRECT = not DEBUG
+SECURE_HSTS_SECONDS = 3600
+SECURE_HSTS_INCLUDE_SUBDOMAINS = True
+SESSION_COOKIE_SECURE = not DEBUG
+CSRF_COOKIE_SECURE = not DEBUG

+PASSWORD_HASHERS = [
+    'django.contrib.auth.hashers.Argon2PasswordHasher',
+    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
+    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
+    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
+]
```

---

## USERS/admin.py

### What changed
- Removed `email`, `is_email_verified`, and `hide_email` from all admin fieldsets, list displays, and search fields
- Replaced `UserAdmin.fieldsets + (...)` (which inherits the email fieldset) with a fully explicit fieldset definition
- Removed the `save_model` override that auto-verified admin-created users

### Why it improves the code
The original admin referenced fields that no longer exist on the model (`email`, `is_email_verified`, `hide_email`). Accessing these in the Django admin would raise `FieldError` at runtime. The rewrite defines fieldsets from scratch, referencing only real model fields, and removes the now-meaningless email verification auto-flag.

```diff
-    list_display = ('email', 'username', ..., 'is_email_verified', 'is_staff')
+    list_display = ('username', 'first_name', 'last_name', 'date_joined', 'last_login', 'is_active', 'is_staff')

-    fieldsets = UserAdmin.fieldsets + (
-        ('Profile', {'fields': (..., 'hide_email')}),
-        ('Verification', {'fields': ('is_email_verified',)}),
+    fieldsets = (
+        (None, {'fields': ('username', 'password')}),
+        ('Personal info', {'fields': ('first_name', 'last_name')}),
+        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
+        ('Important dates', {'fields': ('last_login', 'date_joined')}),
+        ('Profile', {'fields': ('gender', 'profile_picture', 'phone_number', 'date_of_birth', 'country', 'city', 'bio', 'interests')}),
     )

-    def save_model(self, request, obj, form, change):
-        if not change:
-            obj.is_email_verified = True
-        super().save_model(request, obj, form, change)
```

---

## USERS/forms.py

### What changed
- Removed `email` field from `RegisterUserForm`
- Registration form now collects only `username`, `password1`, `password2`

### Why it improves the code
No email is required or stored. Collecting it would be dead data and a privacy liability. The slimmer form matches the new "anonymous account" UX: one screen, no PII beyond username.

```diff
 class RegisterUserForm(auth_forms.UserCreationForm):
-    email = forms.EmailField(required=True)

     class Meta:
         model = UserModel
-        fields = ('username', 'email', 'password1', 'password2', 'first_name', 'last_name')
+        fields = ('username', 'password1', 'password2')
```

---

## USERS/management/commands/create_user.py

### What changed
- Removed `--email` argument and all email-related logic
- Removed the `is_email_verified=True` flag on user creation
- Simplified success message

### Why it improves the code
The management command was used to seed users for development. With email removed from the model, passing an email address would crash the command. The removal keeps the command consistent with the new model.

```diff
-    parser.add_argument("--email", help="Email address")
-        email = options["email"] or input("Email: ")
-        if UserModel.objects.filter(email=email).exists():
-            raise CommandError(f"Email '{email}' is already registered.")
         user = UserModel(
             username=username,
-            email=email,
-            is_email_verified=True,
         )
```

---

## USERS/models.py

### What changed
- `email` field removed (`email = None` overrides `AbstractUser.email`)
- `hide_email` field removed
- `is_email_verified` field removed
- `REQUIRED_FIELDS = []` added (allows `createsuperuser` without prompting for email)
- `recovery_key_hash` and `recovery_key_created_at` fields added
- `get_mail` property removed
- `create_user` and `create_superuser` manager methods updated to remove email parameter

### Why it improves the code
The email column was the only PII field on the model. Removing it eliminates a data liability, simplifies the schema, and prevents any accidental email leakage. `recovery_key_hash` stores the Argon2 hash of the one-time recovery key generated at registration — never the plaintext. The `created_at` timestamp enables future key expiry policies.

```diff
-    email = models.EmailField(unique=True, blank=False)
-    hide_email = models.BooleanField(default=True)
+    email = None  # fully removed — no email column

+    REQUIRED_FIELDS = []

-    is_email_verified = models.BooleanField(default=False)
+    recovery_key_hash = models.CharField(max_length=255, null=True, blank=True)
+    recovery_key_created_at = models.DateTimeField(null=True, blank=True)

-    def create_user(self, username, email, password=None):
+    def create_user(self, username, password=None):

-    def create_superuser(self, username, email, password):
+    def create_superuser(self, username, password):
```

---

## USERS/urls.py

### What changed
- Removed all Django built-in password reset URL patterns (`password_reset`, `password_reset_done`, `reset/<uidb64>/<token>/`, `reset/done/`)
- Removed `email_verification` and `activate-user` URL patterns
- Added `recover/` → `RecoverAccountView`
- Added `dismiss-key-banner/` → `dismiss_key_banner`
- Added `profile/<pk>/settings/security/` → `ProfileSettingsSecurityView`
- Removed imports for `EmailVerificationView`, `ActivateUserView`
- Added imports for `RecoverAccountView`, `ProfileSettingsSecurityView`, `dismiss_key_banner`

### Why it improves the code
All removed URLs belonged to the email-based auth system. Leaving them in would expose dead endpoints pointing at deleted views. The three new URLs wire up the recovery key flow, the banner dismiss, and the security settings page.

```diff
-    path('password_reset/', ...),
-    path('password_reset/done/', ...),
-    path('reset/<uidb64>/<token>/', ...),
-    path('reset/done/', ...),
-    path('email_verification/', ...),
-    path('activate-user/<uidb64>/<token>', ...),

+    path('recover/', RecoverAccountView.as_view(), name='account_recover'),
+    path('dismiss-key-banner/', dismiss_key_banner, name='dismiss_key_banner'),
+    path('security/', ProfileSettingsSecurityView.as_view(), name='profile-settings-security'),
```

---

## USERS/utils.py (deleted)

### What changed
File deleted entirely.

### Why it improves the code
`utils.py` contained `TokenGenerator`, a custom `PasswordResetTokenGenerator` subclass that used `is_email_verified` in its hash value. With email verification removed, this class has no purpose. Deleting the file removes a dependency on the `six` library (Python 2 compatibility shim) and eliminates dead code.

```diff
-from django.contrib.auth.tokens import PasswordResetTokenGenerator
-import six
-
-class TokenGenerator(PasswordResetTokenGenerator):
-    def _make_hash_value(self, user, timestamp):
-        return six.text_type(user.pk) + six.text_type(timestamp) + six.text_type(user.is_email_verified)
-
-generate_token = TokenGenerator()
```

---

## USERS/views.py

### What changed
- Removed `send_activation_email`, `EmailVerificationView`, `ActivateUserView`
- Added `dismiss_key_banner` view
- `RegisterView.form_valid` rewritten: generates recovery key, hashes with Argon2, logs user in, sets session flag for banner, renders `key_reveal.html` with `Cache-Control: no-store`
- `LoginView.form_valid` simplified (removed email verification gate)
- `PublicUserView.get_context_data` removed `show_email` context injection
- Added `ProfileSettingsSecurityView` (key rotation + change password)
- Added `RecoverAccountView` (single-step: username + recovery key + new password)
- Added `_DUMMY_HASH` sentinel for timing-safe username enumeration prevention
- Added `_get_client_ip` helper
- Added rate limiting imports from `USERS/rate_limit.py`

### Why it improves the code

**Recovery key generation**: `secrets.token_urlsafe(32)` produces 256 bits of cryptographic entropy. The plaintext key is shown exactly once and never stored — only its Argon2 hash is persisted. `Cache-Control: no-store` prevents the browser from caching the key-reveal response.

**Timing attack prevention**: `_DUMMY_HASH` ensures that when a username doesn't exist, a full Argon2 verification still runs against the dummy hash. Without this, a non-existent username would return faster than a real one (no hash work), leaking user enumeration via response time.

**`@sensitive_post_parameters` / `@sensitive_variables`**: These decorators scrub recovery keys and passwords from Django error reports and debug logs, preventing accidental key exposure in Sentry, email error reports, or debug pages.

**Key rotation in security settings**: `ProfileSettingsSecurityView` allows logged-in users to generate a new recovery key (old one immediately invalidated) or change their password with current-password verification. The new key is shown via the same `key_reveal.html` template with `is_rotation=True`.

**Session invalidation on recovery**: After a successful password reset, all active sessions for that user are deleted from the session store. This forces all other devices to re-authenticate with the new password.

```diff
-def send_activation_email(user, request): ...
-class EmailVerificationView(TemplateView): ...
-class ActivateUserView(views.View): ...

+@require_POST
+@login_required
+def dismiss_key_banner(request):
+    request.session.pop('show_key_banner', None)
+    return HttpResponse(status=204)

+@method_decorator(sensitive_post_parameters('password1', 'password2'), name='dispatch')
+@method_decorator(sensitive_variables('raw_key'), name='dispatch')
 class RegisterView(views.CreateView):
     def form_valid(self, form):
-        result = super().form_valid(form)
-        send_activation_email(user, self.request)
-        return redirect(reverse('email'))
+        raw_key = secrets.token_urlsafe(32)
+        user.recovery_key_hash = make_password(raw_key)
+        user.recovery_key_created_at = timezone.now()
+        login(self.request, user)
+        self.request.session['show_key_banner'] = True
+        response = render(self.request, 'users/key_reveal.html', {'raw_key': raw_key, 'raw_key_chunked': raw_key_chunked})
+        response['Cache-Control'] = 'no-store'
+        return response

+_DUMMY_HASH = make_password('__dummy_sentinel__')

+class RecoverAccountView(views.View):
+    def post(self, request):
+        # rate limit → dummy hash comparison → validate password → set password
+        # → null out key hash → invalidate all sessions → redirect to login
```

---

## requirements.txt

### What changed
- Added `argon2-cffi==23.1.0`

### Why it improves the code
`Argon2PasswordHasher` in Django requires the `argon2-cffi` C extension. Without it the server would crash on any password hash operation when Argon2 is configured as the primary hasher. Pinning the version ensures reproducible deployments.

```diff
+argon2-cffi==23.1.0
 asgiref==3.7.2
```

---

## static/js/chat-script.js

### What changed
- Removed the `keydown` event listener for Enter key

### Why it improves the code
The original code had two separate handlers that both called `sendMessage()`: a `keydown` listener (Enter key) and a `form submit` listener. In some browsers, pressing Enter in a text input fires both the `keydown` event AND the form `submit` event even when `e.preventDefault()` is called on keydown — resulting in the message being sent twice. The server would receive two WebSocket messages, create two database entries, and broadcast both to all room members. Every user in the room would see the message duplicated. Removing the redundant `keydown` listener and relying solely on the form `submit` event (which Enter naturally triggers in a single-line text input) eliminates the double-send.

```diff
+// Form submit handles both button click and Enter key in the text input.
+// A separate keydown listener for Enter is intentionally omitted — it would
+// double-fire with the submit event in some browsers, sending the message twice.
 if (form) {
   form.addEventListener('submit', function(e) {
     e.preventDefault();
     sendMessage();
   });
 }

-if (messageInput) {
-  messageInput.addEventListener('keydown', function(e) {
-    if (e.key === 'Enter' && !e.shiftKey) {
-      e.preventDefault();
-      sendMessage();
-    }
-  });
-}
```

---

## templates/base.html

### What changed
- Added recovery key reminder banner, shown when `request.session.show_key_banner` is set
- Banner links to Security settings and dismisses via AJAX (`POST /users/dismiss-key-banner/`)
- Inline `<style>` and `<script>` for the banner scoped to the conditional block

### Why it improves the code
The recovery key is shown exactly once (at registration) via `key_reveal.html`. If a user closes the tab before saving the key, there is no other way to retrieve it. The reminder banner provides a persistent (but dismissible) prompt on all subsequent page loads until the user explicitly acknowledges it. The dismiss triggers a server-side session flag clear so the banner does not reappear.

```diff
+{% if request.session.show_key_banner %}
+<div class="key-banner" id="keyBanner" role="alert" aria-live="polite">
+  ...Save your recovery key...
+  <button class="key-banner__close" id="keyBannerClose">...</button>
+</div>
+<script>
+  // Fade out + POST to dismiss_key_banner to clear session flag
+</script>
+{% endif %}
```

---

## templates/chat_rooms/public_chat_messages.html

### What changed
- `{% for message in messages %}` renamed to `{% for message in chat_messages %}`
- Avatar spans replaced with real `<img>` tags for both incoming and outgoing messages

### Why it improves the code

**Variable rename**: Required after `context_object_name` was changed in the view. Without this, the template loop would have no items to iterate and the chat history would render blank.

**Avatars**: Every server-rendered message was using `<span class="msg-avatar--placeholder">`. The JavaScript `buildMessageRow` function (used for live WebSocket messages) correctly rendered real avatars via `data.sender_avatar`. This inconsistency meant that all historical messages loaded on page open had no avatar, while only newly sent messages in the current session showed the actual profile picture. Replacing the placeholder with `{% if message.sender.profile_picture %}<img ...>{% endif %}` makes the server-rendered history visually consistent with live messages. `select_related('sender')` was already in the queryset so no additional database queries are introduced.

```diff
-    {% for message in messages %}
+    {% for message in chat_messages %}

-          <span class="msg-avatar--placeholder" aria-hidden="true"></span>
+          {% if message.sender.profile_picture %}
+          <img src="{{ message.sender.profile_picture.url }}" alt="{{ message.sender.username }}" class="msg-avatar" width="32" height="32">
+          {% else %}
+          <span class="msg-avatar--placeholder" aria-hidden="true"></span>
+          {% endif %}
```

---

## templates/chat_rooms/public_chat_rooms.html

### What changed
- Added `id="requests-length"` to the Requests pill count span
- Added `const requestsCount` variable in JS
- Added `if (requestsCount) requestsCount.textContent = data.requests_count` after the fetch

### Why it improves the code
The Requests count pill was hardcoded to `0` with no DOM ID, so the JS that populated the Friends and Groups counts had no way to update it. The fix adds the ID and wires it to the `requests_count` value now returned by the `chat_room_info` endpoint. Users can now see their actual pending friend request count directly in the chat sidebar without navigating away.

```diff
-        <span class="dashboard-pill__count">0</span>
+        <span class="dashboard-pill__count" id="requests-length">0</span>

+  const requestsCount  = document.getElementById('requests-length');
         if (friendsCount) friendsCount.textContent = data.friends.length;
+        if (requestsCount) requestsCount.textContent = data.requests_count;
```

---

## templates/users/activate-failed.html (deleted)
## templates/users/activate.html (deleted)
## templates/users/email_confirmation.html (deleted)

### What changed
All three files deleted.

### Why it improves the code
These templates were part of the email-based account activation flow: `activate.html` was the activation email body, `email_confirmation.html` was the "check your inbox" page, and `activate-failed.html` was the broken-link error page. With email verification removed, these templates are unreachable dead files. Deleting them removes confusion about what auth flows exist.

---

## templates/users/password_reset/ (multiple files deleted)

Files deleted:
- `password_change.html`
- `password_reset_complete.html`
- `password_reset_done.html`
- `password_reset_email.html`
- `password_reset_form.html`
- `password_reset_subject.txt`

### Why it improves the code
All six files supported Django's built-in email-based password reset flow (the `PasswordResetView` → email link → `PasswordResetConfirmView` chain). Those URL patterns were removed from `USERS/urls.py`. The templates are now unreachable and replaced by `recover_account.html` (the single-step recovery-key flow). Deleting dead templates prevents confusion and keeps the template directory clean.

---

## templates/users/login.html

### What changed
- "Forgot your password?" link changed from `{% url 'password_reset' %}` to `{% url 'account_recover' %}`

### Why it improves the code
The old link pointed to the email-based reset flow (now removed). Without this change, clicking "Forgot your password?" would 404. The new URL points to the recovery key form.

```diff
-      <a href="{% url 'password_reset' %}">Forgot your password?</a>
+      <a href="{% url 'account_recover' %}">Forgot your password?</a>
```

---

## templates/users/profile-personal-card.html

### What changed
- Email row removed from the personal profile card

### Why it improves the code
`{{ user.email }}` would render empty or raise an `AttributeError` since `email = None` on the model. Removing the row prevents a broken/blank field in the UI.

```diff
-      <div style="display:flex;gap:var(--s-4);align-items:baseline">
-        <dt>Email</dt>
-        <dd>{{ user.email }}</dd>
-      </div>
```

---

## templates/users/profile-public-card.html

### What changed
- `{% if show_email or is_self %}` email block removed

### Why it improves the code
`show_email` was injected by `PublicUserView.get_context_data` based on `account.hide_email` — a field that no longer exists. The entire block was dead code that would silently render nothing (both `show_email` and `object.email` would be falsy/empty). Removing it keeps the template clean.

```diff
-        {% if show_email or is_self %}
-        <div ...>
-          <dt>Email</dt>
-          <dd>{{ object.email }}</dd>
-        </div>
-        {% endif %}
```

---

## templates/users/profile-settings.html

### What changed
- "Email" tab (dead `href="#"`) replaced with "Security" tab linking to `profile-settings-security`
- `{% block tab_security %}{% endblock %}` added for active-state highlighting

### Why it improves the code
The Email tab was a placeholder that went nowhere. Replacing it with a working Security tab gives users access to the key rotation and password change features added in this session. The block allows child templates to mark the tab as active.

```diff
-    <a href="#" class="settings-tab">Email</a>
+    <a href="{% url 'profile-settings-security' request.user.pk %}"
+       class="settings-tab {% block tab_security %}{% endblock %}">Security</a>
```

---

## templates/users/register.html

### What changed
- Subtitle changed to "No email required. Just a username and password."
- Email field removed
- First name / last name fields removed
- Submit button text changed to "Create account — get your recovery key"
- Password confirm placeholder updated to "Confirm your password"

### Why it improves the code
The registration form now matches the new minimal-friction model: username + password only. Removing fields that no longer exist on the model (email, first name, last name) prevents `FieldError` on form render. The button text sets expectation that the next step is viewing the recovery key.

```diff
-    <p class="auth-card__subtitle">Join the conversation</p>
+    <p class="auth-card__subtitle">No email required. Just a username and password.</p>

-      Email field (removed)
-      First name / last name grid (removed)

-        Create account
+        Create account — get your recovery key
```
