class HubShellMixin:
    active_tab = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.active_tab:
            ctx["active_tab"] = self.active_tab
        return ctx
