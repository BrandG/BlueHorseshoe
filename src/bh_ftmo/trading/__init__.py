"""BH FTMO order-placement clients.

Separated from `bh_ftmo.data` because data ingestion uses a live (read-only)
OANDA token, while trading uses a separate practice/demo token + account.
The two should never share credentials.
"""
