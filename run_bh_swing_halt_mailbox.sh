#!/usr/bin/env bash
# HALT mailbox poller — out-of-band kill switch. Cron every minute.
# Independent of the trader so a wedged trader cannot block the kill.
cd /root/BlueHorseshoe || exit 1
exec ./run.sh python src/bh_swing/operator/halt_mailbox.py
