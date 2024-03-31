from django import template

register = template.Library()


@register.filter
def placeholder(value, token):
    value.field.widget.attrs['placeholder'] = token
    return value


@register.filter
def element_class(value, token):
    value.field.widget.attrs['class'] = token
    return value


@register.filter
def input_value(value, token):
    value.field.widget.attrs['value'] = token
    return value


@register.filter
def name_value(value, token):
    value.field.widget.attrs['name'] = token
    return value


@register.filter
def type_value(value, token):
    value.field.widget.attrs['type'] = token
    return value


@register.filter
def get_length(value):
    return len(value)