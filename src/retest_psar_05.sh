#!/bin/bash
# Re-test PSAR 0.5x with 30 additional samples

echo "================================================================"
echo "PSAR 0.5x Re-test (30 additional samples)"
echo "Start Time: $(date)"
echo "================================================================"
echo ""

docker exec bluehorseshoe python src/run_phase3_testing.py \
  --indicator PSAR \
  --weight 0.5 \
  --runs 30 \
  --sample-size 1000

echo ""
echo "================================================================"
echo "PSAR 0.5x Re-test Complete!"
echo "End Time: $(date)"
echo "================================================================"
