import os

bind = f"0.0.0.0:{int(os.getenv('PORT', '5000'))}"
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "45"))
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
# Do not log query strings, Authorization headers or request bodies.
access_log_format = "%(h)s %(m)s %(U)s %(s)s %(L)s"
