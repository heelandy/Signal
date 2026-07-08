import pandas as pd
from app import train_model, evaluate_model

price = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=12, freq='MS'),
    'price': [100, 102, 101, 105, 107, 110, 112, 111, 113, 115, 117, 118],
    'gdp': [2.0, 2.1, 2.2, 2.0, 1.9, 2.1, 2.2, 2.3, 2.1, 2.0, 1.9, 2.0],
    'inflation': [3.0, 3.1, 3.2, 3.0, 2.9, 3.0, 3.1, 3.2, 3.0, 2.8, 2.9, 3.0],
})
models, metadata, df_fe = train_model(price)
metrics = evaluate_model(price, models, metadata['features'], metadata)
print(metrics)
