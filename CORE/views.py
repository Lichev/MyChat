from django.views.generic import TemplateView


class HomePage(TemplateView):
    template_name = 'core/index.html'


class ContactSuccessView(TemplateView):
    template_name = 'core/contact-form-success.html'
