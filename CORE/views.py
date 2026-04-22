from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView


class HomePage(TemplateView):
    template_name = 'core/index.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('public_chat_room')
        return super().get(request, *args, **kwargs)


class ContactSuccessView(TemplateView):
    template_name = 'core/contact-form-success.html'


def health(request):
    """Minimal health-check endpoint for load balancer probes. Returns HTTP 200."""
    return JsonResponse({'status': 'ok'})
