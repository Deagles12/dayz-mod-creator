from contextvars import ContextVar

language = ContextVar('language', default='uk')


def set_language(value):
    language.set(value)


def tr(uk, en):
    return en if language.get() == 'en' else uk
