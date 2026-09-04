"""選課日程 (selection-window schedule) from the selcrs front page.

Distinct from ``app.catalog.schedule`` - that one is the ingest CRON
scheduler; this package parses the school's public 選課日程 table
(初選/加退選/棄選/選課確認 windows) and serves it anonymously with a
Redis last-good snapshot.
"""
