# Price Prediction Base

This project provides a simple price prediction script using 3-4 years of historical data and optional macro/microeconomic inputs.

## Files

- `price_prediction.py`: Train a model and predict future prices from historical CSV or Excel data.
- `app.py`: Streamlit web UI for file upload, macro input, and forecast download.
- `notebook.ipynb`: Notebook example for loading data, training, and forecasting.
- `requirements.txt`: Python dependencies.

## Data format

The CSV file must include:

- `date`: date or datetime column
- `price`: numeric target column
- optional numeric macro/micro features, for example:
  - `gdp`
  - `interest_rate`
  - `unemployment_rate`
  - `sales_volume`

Example headers:

```
date,price,gdp,interest_rate,unemployment_rate,sales_volume
2020-01-01,100,2.1,1.5,3.8,12000
...
```

## Run the prediction

Install dependencies:

```bash
pip install -r requirements.txt
```

Train and predict from CSV or Excel:

```bash
python price_prediction.py --data historical_prices.csv --horizon 6 --frequency m --output predictions.csv
```

Fetch history from Yahoo Finance:

```bash
python price_prediction.py --ticker AAPL --start 2020-01-01 --end 2024-01-01 --horizon 6 --frequency m --output predictions.csv
```

Optionally use Alpha Vantage fundamentals as backup or a comparative fundamentals source by providing an API key in the app or by adding relevant columns to your dataset.

Manual entry example:

```bash
python price_prediction.py --manual "date,price\n2024-01-01,100\n2024-02-01,105" --horizon 6 --frequency m --output predictions.csv
```

The Streamlit app also shows technical support/resistance levels and can calculate a P/E-based price target if the dataset includes `eps`.

Calculate a fundamental price target using EPS and a P/E multiple (if `eps` column exists):

```bash
python price_prediction.py --data historical_prices.csv --pe-multiple 16 --horizon 6 --frequency m --output predictions.csv
```

Run the Streamlit UI:

```bash
streamlit run app.py
```

Open `notebook.ipynb` in Jupyter or VS Code to explore the workflow interactively.

## Use future macro/micro inputs

Pass a JSON string or JSON file with macro features for future predicted dates.

Example JSON string:

```bash
python price_prediction.py --data historical_prices.csv --horizon 6 --frequency m --macro '{"gdp": 2.3, "interest_rate": 1.8, "unemployment_rate": 4.2}'
```

Example CSV file (`future_macro.csv`):

```csv
date,gdp,interest_rate,unemployment_rate
2026-05-01,2.4,1.9,4.1
2026-06-01,2.5,2.0,4.0
```

Example JSON file (`future_macro.json`):

```json
[
  {"date": "2026-05-01", "gdp": 2.4, "interest_rate": 1.9},
  {"date": "2026-06-01", "gdp": 2.5, "interest_rate": 2.0}
]
```

Then run:

```bash
python price_prediction.py --data historical_prices.csv --horizon 6 --frequency m --macro future_macro.json
```

## Notes

- The model uses date/time features plus lag and rolling price features.
- If no macro/micro data is provided, the model uses historical values and time-based features.
- For best accuracy, provide 3-4 years of structured monthly or weekly historical data plus macro/microeconomic variables.
