from bluehorseshoe.core.container import create_app_container

container = create_app_container()
db = container.get_database()

# Get the latest date across all symbols using aggregation
pipeline = [
    {'$unwind': '$days'},
    {'$group': {'_id': None, 'max_date': {'$max': '$days.date'}}}
]
result = list(db.historical_prices.aggregate(pipeline))
max_date = result[0]['max_date'] if result else 'None'

# Count symbols that have this max_date
count = db.historical_prices.count_documents({'days.date': max_date})
total = db.historical_prices.count_documents({})

print(f'Latest date in DB: {max_date}')
print(f'Symbols at latest date: {count} / {total}')

# Check SPY specifically
spy = db.historical_prices.find_one({'symbol': 'SPY'})
if spy and spy.get('days'):
    print(f'SPY latest date: {spy["days"][-1]["date"]}')
else:
    print('SPY not found or has no data.')

container.close()
