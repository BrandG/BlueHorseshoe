# Shutdown Checklist - Feb 10, 2026

## ✅ Pre-Shutdown Status

### Active Processes
- ✅ **No background tests running** (Q2 completed)
- ✅ **All results saved** to CSV files
- ✅ **SESSION_HANDOFF.md updated** with current state

### Data Status
- ✅ **Phase 3E Q1 Complete:** 1 winner (ADX 1.0x)
- ✅ **Phase 3E Q2 Complete:** 4 winners (Williams %R × 3, CCI × 1)
- ✅ **Analysis scripts created:** analyze_phase3e_q1.py, analyze_phase3e_q2.py
- ✅ **Results saved:**
  - `src/logs/phase3e_q1_analysis.csv`
  - `src/logs/phase3e_q2_analysis.csv`
  - `src/logs/phase3e_q1.log`
  - `src/logs/phase3e_q2.log`

### Docker Containers
- bluehorseshoe (main app)
- mongo (database)
- redis (task queue)
- bluehorseshoe_worker (Celery worker)
- bluehorseshoe_beat (Celery scheduler)

---

## 🛑 Shutdown Procedure

### Option 1: Graceful Shutdown (Recommended)
```bash
cd /root/BlueHorseshoe/docker
docker compose down
```

This will:
- Stop all containers gracefully
- Preserve data in MongoDB (volume mounted)
- Allow clean restart

### Option 2: Leave Running (if server supports it)
- Containers will survive server reboot if Docker is set to auto-start
- No action needed

---

## 🚀 Restart Procedure (After Server Update)

### 1. Start Docker Containers
```bash
cd /root/BlueHorseshoe/docker
docker compose up -d
```

### 2. Verify Containers
```bash
docker ps
```

Expected containers:
- bluehorseshoe
- mongo
- redis
- bluehorseshoe_worker
- bluehorseshoe_beat

### 3. Check Logs (Optional)
```bash
docker logs bluehorseshoe --tail 50
docker logs bluehorseshoe_worker --tail 50
```

### 4. Verify Data Integrity
```bash
docker exec bluehorseshoe python -c "
from bluehorseshoe.core.database import Database
db = Database()
print('MongoDB connection: OK')
print('Symbols in database:', db.daily_data.count_documents({}))
db.close()
"
```

---

## 📋 Next Session Tasks

### Immediate (if desired):
1. **Continue Phase 3E Testing:**
   ```bash
   cd /root/BlueHorseshoe/src
   nohup ./run_phase3e_q3.sh > logs/phase3e_q3.log 2>&1 &
   ```
   - Q3: Ichimoku + PSAR (6-7 hours)
   - Q4: SuperTrend (3-4 hours)

2. **OR Deploy Current Winners:**
   - Update `src/weights.json` with 5 new indicators
   - Test new configuration
   - Run prediction to verify

### Later:
- Review Phase 3E complete results after Q4
- Deploy all winners together
- Archive old weights.json backups

---

## 📁 Important Files Preserved

### Configuration
- `src/weights.json` - Current production weights (14 indicators)
- `src/weights.json.phase3e_backup` - Backup before Phase 3E
- `docker/.env` - Environment variables

### Results
- `src/logs/phase3e_q1_analysis.csv` - Q1 results
- `src/logs/phase3e_q2_analysis.csv` - Q2 results
- `src/logs/phase3a_backtest_log.csv` - All backtest data
- `src/logs/report_2026-02-09.html` - Monday prediction

### Analysis Scripts
- `src/analyze_phase3e_q1.py` - Q1 analyzer (with validity filter)
- `src/analyze_phase3e_q2.py` - Q2 analyzer (with validity filter)
- `src/run_phase3e_q3.sh` - Q3 test script (ready to run)
- `src/run_phase3e_q4.sh` - Q4 test script (ready to run)

### Documentation
- `SESSION_HANDOFF.md` - Full context for next session
- `SHUTDOWN_CHECKLIST.md` - This file

---

**Status:** ✅ Ready for shutdown
**Next Milestone:** Q3 + Q4 testing, then deploy 5+ winners
**Data Loss Risk:** None (all in MongoDB volumes and git-tracked files)
