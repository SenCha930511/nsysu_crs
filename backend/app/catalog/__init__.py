"""Self-hosted course-catalog pipeline (plan todo 6).

Discovery (qrycourse <select id="YRSM">) -> captcha-parented pagination over
dplycourse.asp -> row normalization -> atomic Postgres snapshot replacement.
The school-facing IO rides ONLY the selcrs adapter / solver loop (TLS,
throttle, captcha lane, backoff are owned there); this package owns parsing,
persistence, scheduling, and ingest bookkeeping.
"""
