#!/usr/bin/env python
"""Find dates and symbols with high scores."""
from bluehorseshoe.core.container import create_app_container

container = create_app_container()
db = container.get_database()

# Get score statistics by date
pipeline = [
    {'$match': {'strategy': 'baseline'}},
    {'$group': {
        '_id': '$date',
        'max_score': {'$max': '$score'},
        'avg_score': {'$avg': '$score'},
        'count': {'$sum': 1}
    }},
    {'$sort': {'max_score': -1}},
    {'$limit': 10}
]

results = list(db.trade_scores.aggregate(pipeline))

print('Dates with highest maximum scores:')
print(f"{'Date':<12} {'Max Score':<12} {'Avg Score':<12} {'Count':<8}")
print('-' * 50)
for r in results:
    print(f"{r['_id']:<12} {r['max_score']:<12.1f} {r['avg_score']:<12.1f} {r['count']:<8}")

# Find high-scoring signals
print('\nTop 20 highest-scoring signals:')
high_scores = list(db.trade_scores.find(
    {'strategy': 'baseline', 'score': {'$gt': 20}},
    {'symbol': 1, 'date': 1, 'score': 1, 'metadata': 1}
).sort('score', -1).limit(20))

print(f"{'Symbol':<8} {'Date':<12} {'Score':<8} {'Strength':<12} {'Discount':<10}")
print('-' * 55)
for s in high_scores:
    meta = s.get('metadata', {})
    strength = meta.get('signal_strength', 'N/A')
    discount = meta.get('atr_discount_used', 'N/A')
    print(f"{s.get('symbol', 'N/A'):<8} {s.get('date', 'N/A'):<12} {s.get('score', 0):<8.1f} {strength:<12} {discount}")

# Count by signal strength
print('\nSignal strength distribution (all baseline signals):')
pipeline_strength = [
    {'$match': {'strategy': 'baseline'}},
    {'$group': {
        '_id': '$metadata.signal_strength',
        'count': {'$sum': 1},
        'avg_score': {'$avg': '$score'}
    }},
    {'$sort': {'avg_score': -1}}
]

strength_dist = list(db.trade_scores.aggregate(pipeline_strength))
print(f"{'Strength':<15} {'Count':<10} {'Avg Score':<12}")
print('-' * 40)
for r in strength_dist:
    print(f"{str(r['_id']):<15} {r['count']:<10} {r['avg_score']:<12.1f}")

container.close()
