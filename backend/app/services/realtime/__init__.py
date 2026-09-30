"""Socket.IO realtime: rooms, the after-commit outbox, and the server.

Deliberately empty. `outbox` is imported by the order path, which runs in
Celery workers too; importing `server` from here would drag the Socket.IO
server into every process that records an order transition.
"""
