import argparse
import json
import os
from datetime import timedelta
from io import StringIO
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def load_data(csv_path: str) -> pd.DataFrame:
    ext = os.path.splitext(csv_path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        df = pd.read_excel(csv_path, parse_dates=["date"])
    else:
        df = pd.read_csv(csv_path, parse_dates=["date"])
    if "price" not in df.columns:
        raise ValueError("The input file must contain a 'price' column.")
    df = df.sort_values("date").reset_index(drop=True)
    return df


def normalize_ticker(ticker: str) -> str:
    return str(ticker).strip().upper().lstrip("$").strip()


def fetch_yahoo_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    ticker = normalize_ticker(ticker)
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty:
        df = yf.Ticker(ticker).history(start=start_date, end=end_date, interval="1d")
    if df.empty:
        raise ValueError(f"No data found for ticker {ticker}. Check symbol and date range.")
    df = df.reset_index()
    df = df.rename(columns={"Date": "date", "Close": "price"})
    if "price" not in df.columns:
        raise ValueError("Yahoo Finance data did not include a Close price column.")
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "price"] + [c for c in df.columns if c not in ["date", "price"]]]


def parse_manual_data(manual_text: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(manual_text), parse_dates=["date"])
    if "price" not in df.columns:
        raise ValueError("Manual entry must contain a 'price' column.")
    df = df.sort_values("date").reset_index(drop=True)
    return df


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["day"] = df["date"].dt.day
    df["dayofweek"] = df["date"].dt.dayofweek
    df["quarter"] = df["date"].dt.quarter
    df["is_month_end"] = df["date"].dt.is_month_end.astype(int)
    df["is_month_start"] = df["date"].dt.is_month_start.astype(int)
    return df


def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "high" in df.columns and "low" in df.columns:
        df["range"] = df["high"] - df["low"]
        df["range_pct"] = df["range"] / df["low"].replace(0, np.nan)
    if "volume" in df.columns:
        df["volume_change_1"] = df["volume"].pct_change()
        df["avg_volume_10"] = df["volume"].rolling(window=10, min_periods=1).mean()
    for window in [5, 10, 20]:
        df[f"sma_{window}"] = df["price"].rolling(window=window, min_periods=1).mean()
        df[f"momentum_{window}"] = df["price"].pct_change(periods=window)
    df["price_diff_1"] = df["price"].diff(1)
    return df


def support_resistance_levels(df: pd.DataFrame, lookback: int = 20) -> dict:
    df = df.copy()
    if "high" in df.columns and "low" in df.columns:
        resistance = df["high"].rolling(window=lookback, min_periods=1).max().iloc[-1]
        support = df["low"].rolling(window=lookback, min_periods=1).min().iloc[-1]
    else:
        resistance = df["price"].rolling(window=lookback, min_periods=1).max().iloc[-1]
        support = df["price"].rolling(window=lookback, min_periods=1).min().iloc[-1]
    return {"support": float(support), "resistance": float(resistance)}


def fundamental_price_target(df: pd.DataFrame, pe_multiple: float | None = None) -> float | None:
    if pe_multiple is None:
        return None
    if "eps" in df.columns:
        eps = df["eps"].iloc[-1]
        return float(eps * pe_multiple)
    if "earnings" in df.columns:
        earnings = df["earnings"].iloc[-1]
        shares = df["shares_outstanding"].iloc[-1] if "shares_outstanding" in df.columns else None
        if shares is not None:
            return float((earnings / shares) * pe_multiple)
    return None


def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    df = add_time_features(df)
    df = compute_technical_indicators(df)
    df = df.copy()
    df["price_lag_1"] = df["price"].shift(1)
    df["price_lag_2"] = df["price"].shift(2)
    df["price_lag_3"] = df["price"].shift(3)
    df["price_roll_3"] = df["price"].rolling(window=3, min_periods=1).mean()
    df["price_roll_6"] = df["price"].rolling(window=6, min_periods=1).mean()
    df = df.dropna().reset_index(drop=True)
    return df


def prepare_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    features = [c for c in df.columns if c not in ["date", "price"]]
    X = df[features].select_dtypes(include=[np.number]).copy()
    y = df["price"].copy()
    return X, y


def make_future_dates(last_date: pd.Timestamp, periods: int, frequency: str) -> pd.DatetimeIndex:
    if frequency.lower() in ["d", "day", "daily"]:
        return pd.date_range(start=last_date + timedelta(days=1), periods=periods, freq="D")
    if frequency.lower() in ["w", "week", "weekly"]:
        return pd.date_range(start=last_date + timedelta(days=7), periods=periods, freq="W")
    if frequency.lower() in ["m", "month", "monthly"]:
        return pd.date_range(start=last_date + pd.offsets.MonthBegin(1), periods=periods, freq="MS")
    if frequency.lower() in ["q", "quarter", "quarterly"]:
        return pd.date_range(start=last_date + pd.offsets.QuarterBegin(startingMonth=1), periods=periods, freq="QS")
    return pd.date_range(start=last_date + timedelta(days=1), periods=periods, freq="D")


def build_model() -> Pipeline:
    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        (
            "model",
            HistGradientBoostingRegressor(
                max_iter=500,
                learning_rate=0.05,
                max_depth=6,
                early_stopping=True,
                random_state=42,
            ),
        ),
    ])
    return pipeline


def train_model(df: pd.DataFrame) -> tuple[Pipeline, dict]:
    df_fe = feature_engineering(df)
    X, y = prepare_matrix(df_fe)
    if X.shape[1] == 0:
        raise ValueError("No numeric training features were found. Ensure your historical data and macro columns are numeric.")
    model = build_model()
    model.fit(X, y)
    metadata = {
        "frequency": pd.infer_freq(df["date"]) or "M",
        "features": X.columns.tolist(),
    }
    return model, metadata


def create_future_frame(last_row: pd.Series, future_dates: pd.DatetimeIndex, future_macro: pd.DataFrame) -> pd.DataFrame:
    rows = []
    last_values = last_row.copy()
    for dt in future_dates:
        row = pd.Series(last_values, copy=True)
        row["date"] = dt
        row["price"] = np.nan
        if future_macro is not None and dt in future_macro.index:
            for col in future_macro.columns:
                row[col] = future_macro.loc[dt, col]
        rows.append(row)
        last_values = row
    future_df = pd.DataFrame(rows).reset_index(drop=True)
    return future_df


def load_macro_file(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            raw_text = f.read()
        return parse_macro_json(raw_text, None)
    if ext in [".csv"]:
        df = pd.read_csv(path, parse_dates=["date"])
    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(path, parse_dates=["date"])
    else:
        raise ValueError("Unsupported macro file format. Use JSON, CSV, XLSX, or XLS.")
    if "date" in df.columns:
        df = df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])
    return df


def parse_macro_json(text: str, future_dates: pd.DatetimeIndex | None) -> pd.DataFrame:
    data = json.loads(text)
    if isinstance(data, dict):
        if future_dates is None:
            raise ValueError("Future dates are required for dict macro input.")
        return pd.DataFrame([data], index=[future_dates[0]]).reindex(future_dates).ffill()
    if isinstance(data, list):
        future_df = pd.DataFrame(data)
        if "date" in future_df.columns:
            future_df["date"] = pd.to_datetime(future_df["date"])
            future_df = future_df.set_index("date")
        else:
            if future_dates is None:
                raise ValueError("Future dates are required for list macro input without date columns.")
            future_df.index = future_dates
        return future_df.reindex(future_dates).ffill()
    raise ValueError("Macro input must be a JSON object or JSON list.")


def parse_macro_input(text: str, future_dates: pd.DatetimeIndex) -> pd.DataFrame:
    if os.path.exists(text):
        df = load_macro_file(text)
        return df.reindex(future_dates).ffill()
    return parse_macro_json(text, future_dates)


def forecast_macro_by_growth(df: pd.DataFrame, future_dates: pd.DatetimeIndex, macro_cols: list[str]) -> pd.DataFrame:
    history = df.set_index("date")[macro_cols].dropna(how="all")
    if history.empty:
        raise ValueError("No macro/microeconomic features found in the historical dataset to forecast.")
    growth = history.pct_change().mean()
    last = history.iloc[-1].copy()
    rows = []
    current = last.copy()
    for _ in range(len(future_dates)):
        current = current * (1 + growth.fillna(0))
        rows.append(current.to_dict())
    future_df = pd.DataFrame(rows, index=future_dates)
    return future_df


def predict_future(
    model: Pipeline,
    df: pd.DataFrame,
    future_horizon: int,
    frequency: str,
    future_macro: pd.DataFrame | None = None,
    feature_columns: list[str] | None = None,
) -> pd.DataFrame:
    last_row = df.iloc[-1]
    future_dates = make_future_dates(last_row["date"], future_horizon, frequency)
    future_df = create_future_frame(last_row, future_dates, future_macro)
    full_df = pd.concat([df, future_df], ignore_index=True, sort=False)
    full_df = add_time_features(full_df)
    full_df["price_lag_1"] = full_df["price"].shift(1)
    full_df["price_lag_2"] = full_df["price"].shift(2)
    full_df["price_lag_3"] = full_df["price"].shift(3)
    full_df["price_roll_3"] = full_df["price"].rolling(window=3, min_periods=1).mean()
    full_df["price_roll_6"] = full_df["price"].rolling(window=6, min_periods=1).mean()
    full_df["price_diff_1"] = full_df["price"].diff(1)
    future_slice = full_df[full_df["date"].isin(future_dates)].copy()

    if feature_columns is None:
        feature_columns = getattr(model, "feature_names_in_", None)
    if feature_columns is None:
        feature_columns = [c for c in future_slice.columns if c not in ["date", "price"]]

    for col in feature_columns:
        if col not in future_slice.columns:
            future_slice[col] = np.nan

    future_X = future_slice[feature_columns].copy()
    predictions = model.predict(future_X)
    future_slice["predicted_price"] = predictions
    return future_slice[["date", "predicted_price"] + [c for c in future_slice.columns if c not in ["date", "price", "predicted_price"]]]


def evaluate_model(df: pd.DataFrame, model: Pipeline) -> dict:
    df_fe = feature_engineering(df)
    X, y = prepare_matrix(df_fe)
    predicted = model.predict(X)
    mae = np.mean(np.abs(predicted - y))
    rmse = np.sqrt(np.mean((predicted - y) ** 2))
    return {"mae": float(mae), "rmse": float(rmse)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a price prediction model from historical data.")
    parser.add_argument("--data", help="Path to the historical CSV or Excel file.")
    parser.add_argument("--ticker", help="Yahoo Finance ticker symbol to fetch historical price data.")
    parser.add_argument("--start", help="Start date for Yahoo Finance data (YYYY-MM-DD).")
    parser.add_argument("--end", help="End date for Yahoo Finance data (YYYY-MM-DD).")
    parser.add_argument("--manual", help="Manual CSV text with date and price columns.")
    parser.add_argument("--horizon", type=int, default=6, help="Number of future periods to predict.")
    parser.add_argument(
        "--frequency",
        choices=["d", "w", "m", "q", "daily", "weekly", "monthly", "quarterly"],
        default="m",
        help="Time frequency for the future predictions.",
    )
    parser.add_argument(
        "--macro",
        help="Optional JSON string, CSV/Excel path, or JSON file containing future macro/micro features.",
    )
    parser.add_argument(
        "--macro-method",
        choices=["static", "growth", "none"],
        default="static",
        help="If set to growth, forecast macro features from historical trends when no future macro values are provided.",
    )
    parser.add_argument("--pe-multiple", type=float, help="Optional P/E multiple for a fundamental price target.")
    parser.add_argument("--output", default="predictions.csv", help="Output CSV file for the future predictions.")
    args = parser.parse_args()

    if args.ticker:
        if not args.start or not args.end:
            raise ValueError("--start and --end are required when using --ticker.")
        df = fetch_yahoo_data(args.ticker, args.start, args.end)
    elif args.manual:
        df = parse_manual_data(args.manual)
    elif args.data:
        if not os.path.exists(args.data):
            raise FileNotFoundError(f"Data file not found: {args.data}")
        df = load_data(args.data)
    else:
        raise ValueError("Provide --data, --ticker, or --manual to load historical price data.")

    model, metadata = train_model(df)
    metrics = evaluate_model(df, model)

    future_macro = None
    future_dates = make_future_dates(df.iloc[-1]["date"], args.horizon, args.frequency)
    if args.macro:
        future_macro = parse_macro_input(args.macro, future_dates)
    elif args.macro_method == "growth":
        macro_cols = [c for c in df.columns if c not in ["date", "price"]]
        if macro_cols:
            future_macro = forecast_macro_by_growth(df, future_dates, macro_cols)

    predictions = predict_future(model, df, args.horizon, args.frequency, future_macro, metadata["features"])
    predictions.to_csv(args.output, index=False)

    target = fundamental_price_target(df, args.pe_multiple) if args.pe_multiple else None
    levels = support_resistance_levels(df)

    print("Model trained successfully.")
    print("Metadata:", json.dumps(metadata, indent=2))
    print("Evaluation:", json.dumps(metrics, indent=2))
    if target is not None:
        print(f"Fundamental price target (EPS x P/E): {target:.2f}")
    print("Support/resistance levels:", json.dumps(levels, indent=2))
    print(f"Predictions saved to {args.output}")
    print("Sample predictions:")
    print(predictions.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
