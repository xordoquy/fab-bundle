{% if base_settings %}from {{ base_settings }} import *{% endif %}

DEBUG = False
TEMPLATE_DEBUG = True

ADMINS = ({% for admin in admins %}
    ('{{ admin.name }}', '{{ admin.email }}'),{% endfor %}
)
MANAGERS = ADMINS
SEND_BROKEN_LINK_EMAILS = True

ALLOWED_HOSTS = ["{{ http_host }}", "www.{{ http_host }}"]

SECRET_KEY = '{{ secret_key }}'

BASE_URL = 'http{% if ssl_cert %}s{% endif %}://{{ http_host }}'
MEDIA_ROOT = '{{ media_root }}'
MEDIA_URL = BASE_URL + '/media/'

{% if staticfiles %}
STATIC_ROOT = '{{ static_root }}'
STATIC_URL = BASE_URL + '/static/'
{% endif %}

{% if cache >= 0 %}
CACHES = {
    'default': {
        'BACKEND': 'redis_cache.RedisCache',
        'LOCATION': 'localhost:6379',
        'OPTIONS': {
            'DB': {{ cache }},
        },
    },
}
MESSAGE_STORAGE = 'django.contrib.messages.storage.fallback.FallbackStorage'
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
{% if rq %}
RQ = {
    'db': {{ cache }},
}
{% endif %}
{% endif %}

{% if databases %}
DATABASES = {
    {% for short_name, database in databases.iteritems() %}
    '{{short_name}}': { {% for key, value in database.iteritems() %}
        '{{key}}': '{{value}}',{% endfor %}
    }
    {% endfor %}
}
{% else %}
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': '{{ http_host }}',
        'USER': 'postgres',
    }
}
{% endif %}

{% if sentry_dsn %}
SENTRY_DSN = '{{ sentry_dsn }}'
{% endif %}

{% if email %}
EMAIL_SUBJECT_PREFIX = '[{{ http_host }}] '
SERVER_EMAIL = DEFAULT_FROM_EMAIL = '{{ email.from }}'
{% if email.host %}EMAIL_HOST = '{{ email.host }}'{% endif %}
{% if email.user %}EMAIL_HOST_USER = '{{ email.user }}'{% endif %}
{% if email.password %}EMAIL_HOST_PASSWORD = '{{ email.password }}'{% endif %}
{% if email.port %}EMAIL_PORT = {{ email.port }}{% endif %}
{% if email.backend %}EMAIL_BACKEND = '{{ email.backend }}'{% endif %}
{% if email.tls %}EMAIL_USE_TLS = True{% endif %}
{% endif %}

SESSION_COOKIE_HTTPONLY = True{% if ssl_cert %}
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTOCOL', 'https'){% endif %}

{% if settings %}{{ settings|safe }}{% endif %}
