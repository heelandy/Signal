import json
import os
from datetime import date, timedelta
from io import StringIO
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV, LogisticRegression
from sklearn.metrics import precision_score, recall_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MACRO_FEATURE_ALIASES = {
    "gdp": ["gdp", "gross domestic product"],
    "inflation": ["inflation", "cpi", "ppi", "consumer price index", "producer price index"],
    "unemployment_rate": ["unemployment_rate", "unemployment rate", "unemployment"],
    "interest_rate": ["interest_rate", "interest rate", "fed funds rate", "federal funds rate", "policy rate"],
    "trade_balance": ["trade_balance", "trade balance", "net exports", "exports minus imports"],
}


def normalize_macro_name(name: str) -> str:
    normalized = str(name).strip().lower().replace(" ", "_")
    for canonical, aliases in MACRO_FEATURE_ALIASES.items():
        alias_keys = [alias.replace(" ", "_") for alias in aliases]
        if normalized == canonical or normalized in alias_keys:
            return canonical
    return normalized


def normalize_macro_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns=lambda col: normalize_macro_name(col))


def get_default_macro_input() -> str:
    return json.dumps(
        {
            "gdp": 2.1,
            "inflation": 3.3,
            "unemployment_rate": 4.3,
            "interest_rate": 3.74,
            "trade_balance": -57.35,
        },
        indent=2,
    )


def load_data(file) -> pd.DataFrame:
    ext = os.path.splitext(file.name)[1].lower()
    if ext in [".xlsx", ".xls"]:
        df = pd.read_excel(file, parse_dates=["date"])
    else:
        df = pd.read_csv(file, parse_dates=["date"])
    if "price" not in df.columns:
        st.error("Uploaded file must contain a 'price' column.")
        st.stop()
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
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join([str(level) for level in col if str(level)]) for col in df.columns.values]
    df = df.reset_index()
    df = df.rename(columns={"Date": "date", "Close": "price", "Adj Close": "price"})
    if "price" not in df.columns:
        close_columns = [c for c in df.columns if "close" in str(c).lower() or str(c).lower().endswith("_price")]
        if close_columns:
            df = df.rename(columns={close_columns[0]: "price"})
    if "price" not in df.columns:
        raise ValueError("Yahoo Finance data did not include a Close price column.")
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "price"] + [c for c in df.columns if c not in ["date", "price"]]]


def parse_manual_entry(manual_text: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(manual_text), parse_dates=["date"])
    if "price" not in df.columns:
        st.error("Manual entry must contain a 'price' column.")
        st.stop()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def support_resistance_levels(df: pd.DataFrame, lookback: int = 20) -> dict:
    if "high" in df.columns and "low" in df.columns:
        resistance = df["high"].rolling(window=lookback, min_periods=1).max().iloc[-1]
        support = df["low"].rolling(window=lookback, min_periods=1).min().iloc[-1]
    else:
        resistance = df["price"].rolling(window=lookback, min_periods=1).max().iloc[-1]
        support = df["price"].rolling(window=lookback, min_periods=1).min().iloc[-1]
    return {"support": float(support), "resistance": float(resistance)}


def fundamental_price_target(df: pd.DataFrame, pe_multiple: float) -> float | None:
    if pe_multiple <= 0:
        return None
    if "eps" in df.columns:
        eps = df["eps"].iloc[-1]
        return float(eps * pe_multiple)
    if "earnings" in df.columns:
        earnings = df["earnings"].iloc[-1]
        if "shares_outstanding" in df.columns:
            shares = df["shares_outstanding"].iloc[-1]
            return float((earnings / shares) * pe_multiple)
    return None


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "price" in df.columns:
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
    for col in df.columns:
        if col not in ["date", "price"] and df[col].dtype == object:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "price"]).sort_values("date").reset_index(drop=True)
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
    df["return_1d"] = df["price"].pct_change()
    df["vol_10"] = df["return_1d"].rolling(window=10, min_periods=1).std()
    for window in [5, 10, 20]:
        df[f"sma_{window}"] = df["price"].rolling(window=window, min_periods=1).mean()
        df[f"ema_{window}"] = df["price"].ewm(span=window, min_periods=1).mean()
        df[f"momentum_{window}"] = df["price"].pct_change(periods=window)
    df["price_vs_sma20"] = (df["price"] - df["sma_20"]) / df["sma_20"].replace(0, np.nan)
    df["range_5"] = df["price"].rolling(window=5, min_periods=1).apply(lambda x: x.max() - x.min())
    df["ema_12"] = df["price"].ewm(span=12, min_periods=1).mean()
    df["ema_26"] = df["price"].ewm(span=26, min_periods=1).mean()
    df["macd"] = df["ema_12"] - df["ema_26"]
    df["macd_signal"] = df["macd"].ewm(span=9, min_periods=1).mean()
    delta = df["price"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14, min_periods=1).mean()
    avg_loss = loss.rolling(window=14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))
    if "high" in df.columns and "low" in df.columns:
        high_low = df["high"] - df["low"]
        df["atr_14"] = high_low.rolling(window=14, min_periods=1).mean()
    else:
        df["atr_14"] = delta.abs().rolling(window=14, min_periods=1).mean()
    return df


def compute_macro_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for macro in ["gdp", "inflation", "unemployment_rate", "interest_rate", "trade_balance"]:
        if macro in df.columns:
            df[f"{macro}_chg"] = df[macro].pct_change()
            df[f"{macro}_roll_3"] = df[macro].rolling(window=3, min_periods=1).mean()
    return df


def compute_quant_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "return_1d" not in df.columns:
        df["return_1d"] = df["price"].pct_change()
    df["volatility_10"] = df["return_1d"].rolling(window=10, min_periods=1).std()
    df["volatility_20"] = df["return_1d"].rolling(window=20, min_periods=1).std()
    for window in [5, 10, 20]:
        df[f"return_{window}"] = df["price"].pct_change(periods=window)
    df["momentum_20"] = df["price"].pct_change(periods=20).fillna(0)
    df["mean_reversion_20"] = df["price"] - df["price"].rolling(window=20, min_periods=1).mean()
    df["zscore_20"] = (
        df["return_1d"] - df["return_1d"].rolling(window=20, min_periods=1).mean()
    ) / df["return_1d"].rolling(window=20, min_periods=1).std().replace(0, np.nan)
    return df


def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_data(df)
    df = add_time_features(df)
    df = compute_technical_indicators(df)
    df = compute_macro_features(df)
    df = compute_quant_features(df)
    df = df.copy()
    df["price_lag_1"] = df["price"].shift(1)
    df["price_lag_2"] = df["price"].shift(2)
    df["price_lag_3"] = df["price"].shift(3)
    df["price_roll_3"] = df["price"].rolling(window=3, min_periods=1).mean()
    df["price_roll_6"] = df["price"].rolling(window=6, min_periods=1).mean()
    df["price_diff_1"] = df["price"].diff(1)
    df = df.dropna(subset=["date", "price"]).reset_index(drop=True)
    return df


def prepare_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    features = [c for c in df.columns if c not in ["date", "price"]]
    X = df[features].select_dtypes(include=[np.number]).copy()
    y = df["price"].copy()
    return X, y


def assign_market_regime(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "sma_20" not in df.columns or "return_1d" not in df.columns:
        df = compute_technical_indicators(df)
    df["trend_slope_20"] = df["sma_20"] - df["sma_20"].shift(20)
    df["vol_20"] = df["return_1d"].rolling(window=20, min_periods=1).std()
    df["market_regime"] = np.select(
        [
            df["vol_20"] > 0.04,
            (df["trend_slope_20"] > 0) & (df["vol_20"] > 0.02),
            (df["trend_slope_20"] < 0) & (df["vol_20"] > 0.02),
        ],
        ["High volatility", "Bull", "Bear"],
        default="Sideways",
    )
    df.loc[df["trend_slope_20"].isna(), "market_regime"] = "Neutral"
    return df


def encode_market_regime(df: pd.DataFrame) -> pd.DataFrame:
    if "market_regime" not in df.columns:
        return df
    regime_dummies = pd.get_dummies(df["market_regime"], prefix="regime")
    return pd.concat([df, regime_dummies], axis=1)


def compute_forecast_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = add_time_features(df)
    df = compute_technical_indicators(df)
    df = compute_macro_features(df)
    df = compute_quant_features(df)
    df["price_lag_1"] = df["price"].shift(1)
    df["price_lag_2"] = df["price"].shift(2)
    df["price_lag_3"] = df["price"].shift(3)
    df["price_roll_3"] = df["price"].rolling(window=3, min_periods=1).mean()
    df["price_roll_6"] = df["price"].rolling(window=6, min_periods=1).mean()
    df["price_diff_1"] = df["price"].diff(1)
    df = assign_market_regime(df)
    df["market_regime"] = df["market_regime"].ffill().fillna("Neutral")
    df = encode_market_regime(df)
    return df


def fit_regime_models(X: pd.DataFrame, y: pd.Series, regimes: pd.Series) -> dict[str, Any]:
    regime_models: dict[str, Any] = {}
    if regimes is None or regimes.empty:
        return regime_models
    for regime in regimes.dropna().unique():
        mask = regimes == regime
        if mask.sum() >= max(10, X.shape[1] * 2):
            try:
                model = make_regressor_pipeline(
                    HistGradientBoostingRegressor(
                        max_iter=300,
                        learning_rate=0.05,
                        max_depth=5,
                        early_stopping=True,
                        random_state=42,
                    )
                )
                model.fit(X.loc[mask], y.loc[mask])
                regime_models[str(regime)] = model
            except Exception:
                pass
    return regime_models


def regime_adjusted_predict(models: dict[str, Any], X: pd.DataFrame, regimes: pd.Series | None, metadata: dict | None = None) -> tuple[np.ndarray, np.ndarray | None]:
    predictions, direction_prob = ensemble_predict(models, X)
    if metadata is not None:
        regime_models = metadata.get("regime_models") or {}
    else:
        regime_models = {}
    if not regime_models or regimes is None:
        return predictions, direction_prob
    regime_adj_preds = np.array(predictions, copy=True)
    for regime, model in regime_models.items():
        mask = regimes == regime
        if mask.any():
            try:
                regime_vals = model.predict(X.loc[mask])
                regime_adj_preds[mask] = 0.7 * regime_adj_preds[mask] + 0.3 * regime_vals
            except Exception:
                pass
    return regime_adj_preds, direction_prob


def drop_highly_correlated_features(X: pd.DataFrame, threshold: float = 0.90) -> pd.DataFrame:
    corr = X.corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    to_drop = [column for column in upper.columns if any(upper[column] > threshold)]
    return X.drop(columns=to_drop, errors="ignore")


def get_feature_importance(X: pd.DataFrame, y: pd.Series) -> pd.Series:
    importances = pd.Series(0.0, index=X.columns)
    if X.shape[1] == 0 or X.shape[0] < 5:
        return importances
    X_imp = X.fillna(0)
    try:
        rf = RandomForestRegressor(n_estimators=200, max_depth=8, random_state=42)
        rf.fit(X_imp, y)
        importances += pd.Series(rf.feature_importances_, index=X.columns)
    except Exception:
        pass
    try:
        gb = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=6, random_state=42)
        gb.fit(X, y)
        importances += pd.Series(gb.feature_importances_, index=X.columns)
    except Exception:
        pass
    if importances.sum() > 0:
        importances /= 2
    return importances


def select_predictive_features(df: pd.DataFrame, target_col: str = "price") -> list[str]:
    X, y = prepare_matrix(df)
    X = drop_highly_correlated_features(X)
    importances = get_feature_importance(X, y)
    selected = importances[importances >= 0.01].sort_values(ascending=False).index.tolist()
    if not selected:
        selected = importances.sort_values(ascending=False).head(min(30, len(importances))).index.tolist()
    if not selected:
        selected = X.columns.tolist()
    return selected


def apply_pca_if_needed(X: pd.DataFrame, variance_threshold: float = 0.95) -> tuple[pd.DataFrame, PCA | None]:
    if X.shape[1] <= 25:
        return X, None
    pca = PCA(n_components=variance_threshold, random_state=42)
    transformed = pca.fit_transform(X.fillna(0))
    columns = [f"pca_{i+1}" for i in range(transformed.shape[1])]
    return pd.DataFrame(transformed, columns=columns, index=X.index), pca


def make_regressor_pipeline(estimator) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", estimator),
    ])


def make_classifier_pipeline(estimator) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", estimator),
    ])


def fit_ensemble_models(X: pd.DataFrame, y: pd.Series) -> dict[str, Any]:
    models: dict[str, Any] = {
        "rf": make_regressor_pipeline(RandomForestRegressor(n_estimators=200, max_depth=8, random_state=42)),
        "gb": make_regressor_pipeline(HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05, max_depth=6, early_stopping=True, random_state=42)),
        "ridge": make_regressor_pipeline(RidgeCV(alphas=[0.1, 1.0, 10.0], scoring="neg_mean_squared_error", cv=3)),
    }
    if X.shape[0] >= 60:
        models["mlp"] = make_regressor_pipeline(MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42))
    else:
        models["mlp"] = None
    direction = (y.diff().fillna(0) > 0).astype(int)
    models["direction"] = make_classifier_pipeline(LogisticRegression(max_iter=500, solver="liblinear", C=1.0))
    for key in ["rf", "gb", "ridge"]:
        models[key].fit(X, y)
    if models["mlp"] is not None:
        try:
            models["mlp"].fit(X, y)
        except Exception:
            models["mlp"] = None
    models["direction"].fit(X, direction)
    return models


def ensemble_predict(models: dict[str, Any], X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray | None]:
    predictions = []
    for key in ["rf", "gb", "ridge", "mlp"]:
        model = models.get(key)
        if model is not None:
            predictions.append(model.predict(X))
    if not predictions:
        raise ValueError("No trained regressors available for ensemble prediction.")
    avg_prediction = np.mean(np.vstack(predictions), axis=0)
    direction_prob = None
    if "direction" in models and models["direction"] is not None:
        try:
            direction_prob = models["direction"].predict_proba(X)[:, 1]
        except Exception:
            direction_prob = None
    return avg_prediction, direction_prob


def max_drawdown(prices: pd.Series) -> float:
    running_max = prices.cummax()
    drawdown = (prices - running_max) / running_max
    return float(drawdown.min()) if not drawdown.empty else 0.0


def compute_profit_factor(actual_returns: pd.Series, predicted_direction: np.ndarray) -> float:
    if len(actual_returns) == 0 or len(predicted_direction) == 0:
        return 0.0
    direction = np.sign(predicted_direction)
    wins = actual_returns[direction == 1].sum()
    losses = -actual_returns[direction < 1].sum()
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses)


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


def train_model(df: pd.DataFrame) -> tuple[dict[str, Any], dict, pd.DataFrame]:
    df_fe = feature_engineering(df)
    df_fe = assign_market_regime(df_fe)
    df_fe = encode_market_regime(df_fe)
    selected_features = select_predictive_features(df_fe)
    X = df_fe[selected_features].copy()
    y = df_fe["price"].copy()

    if X.shape[1] == 0:
        raise ValueError("No numeric training features were found. Ensure your historical data and macro columns are numeric.")

    X_pca, pca = apply_pca_if_needed(X)
    models = fit_ensemble_models(X_pca, y)
    regime_models = fit_regime_models(X_pca, y, df_fe["market_regime"])
    feature_importances = get_feature_importance(drop_highly_correlated_features(X), y)
    metadata = {
        "frequency": pd.infer_freq(df["date"]) or "M",
        "features": X.columns.tolist(),
        "selected_features": selected_features,
        "feature_importances": feature_importances.sort_values(ascending=False).to_dict(),
        "pca": pca,
        "pca_components": None if pca is None else pca.n_components_,
        "regime_counts": df_fe["market_regime"].value_counts().to_dict(),
        "regime_models": regime_models,
    }
    return models, metadata, df_fe


def create_future_frame(last_row: pd.Series, future_dates: pd.DatetimeIndex, future_macro: pd.DataFrame | None) -> pd.DataFrame:
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


def parse_macro_text(text: str, future_dates: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    text = text.strip()
    if not text:
        raise ValueError("Manual macro input is empty.")
    if text.startswith("{") or text.startswith("["):
        data = json.loads(text)
        if isinstance(data, dict):
            normalized = {normalize_macro_name(k): v for k, v in data.items()}
            if future_dates is None:
                raise ValueError("Future dates are required for JSON macro object input.")
            future_df = pd.DataFrame([normalized], index=[future_dates[0]]).reindex(future_dates).ffill()
            return normalize_macro_dataframe(future_df)
        if isinstance(data, list):
            future_df = pd.DataFrame(data)
            future_df = normalize_macro_dataframe(future_df)
            if "date" in future_df.columns:
                future_df["date"] = pd.to_datetime(future_df["date"])
                future_df = future_df.set_index("date")
            else:
                if future_dates is None:
                    raise ValueError("Future dates are required for JSON macro list input without date column.")
                future_df.index = future_dates
            return future_df.reindex(future_dates).ffill()
        raise ValueError("Macro input must be a JSON object or JSON list.")

    df = pd.read_csv(StringIO(text), parse_dates=["date"]) if "date" in text.lower() else pd.read_csv(StringIO(text))
    df = normalize_macro_dataframe(df)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    elif future_dates is not None:
        df.index = future_dates
    else:
        raise ValueError("Manual macro input must include a 'date' column or provide future dates.")
    return df.reindex(future_dates if future_dates is not None else df.index).ffill()


def parse_macro_input(macro_input: str, future_dates: pd.DatetimeIndex) -> pd.DataFrame:
    return parse_macro_text(macro_input, future_dates)


def load_macro_file(uploaded_file) -> pd.DataFrame:
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext in [".xlsx", ".xls"]:
        df = pd.read_excel(uploaded_file, parse_dates=["date"])
    else:
        df = pd.read_csv(uploaded_file, parse_dates=["date"])
    if "date" not in df.columns:
        st.error("Macro file must contain a 'date' column.")
        st.stop()
    df = df.set_index(pd.to_datetime(df["date"])).drop(columns=["date"])
    return normalize_macro_dataframe(df)


def merge_macro_history(price_df: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame:
    merged = price_df.merge(
        macro_df.reset_index().rename(columns={"index": "date"}),
        on="date",
        how="left",
    )
    return merged


def fetch_alpha_vantage_overview(symbol: str, api_key: str) -> dict[str, float]:
    if not api_key:
        raise ValueError("Alpha Vantage API key is required.")
    symbol = normalize_ticker(symbol)
    base_url = "https://www.alphavantage.co/query"
    params = {"function": "OVERVIEW", "symbol": symbol, "apikey": api_key}
    url = f"{base_url}?{urlencode(params)}"
    with urlopen(url, timeout=30) as response:
        data = json.load(response)
    if not data or "Symbol" not in data:
        if "Note" in data:
            raise ValueError(data["Note"])
        if "Error Message" in data:
            raise ValueError(data["Error Message"])
        raise ValueError("Alpha Vantage did not return company overview data.")
    numeric_fields = {
        "MarketCapitalization": "market_capitalization",
        "EPS": "eps",
        "PERatio": "pe_ratio",
        "PEGRatio": "peg_ratio",
        "PriceToBookRatio": "price_to_book",
        "DividendYield": "dividend_yield",
        "EBITDA": "ebitda",
        "RevenueTTM": "revenue_ttm",
        "ProfitMargin": "profit_margin",
        "OperatingMarginTTM": "operating_margin_ttm",
        "ReturnOnEquityTTM": "return_on_equity_ttm",
        "GrossProfitTTM": "gross_profit_ttm",
    }
    overview = {}
    for key, feature_name in numeric_fields.items():
        value = data.get(key)
        if value is None or value == "None" or str(value).strip() == "":
            continue
        try:
            timeline_value = float(str(value).replace(",", ""))
            overview[feature_name] = timeline_value
        except ValueError:
            continue
    if not overview:
        raise ValueError("Alpha Vantage overview returned no usable numeric fundamentals.")
    return overview


def merge_alpha_vantage_overview(df: pd.DataFrame, overview_data: dict[str, float]) -> pd.DataFrame:
    if not overview_data:
        return df
    for key, value in overview_data.items():
        df[key] = value
    return df


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


def detect_market_regime(df: pd.DataFrame) -> str:
    if len(df) < 20 or "sma_20" not in df.columns or "return_1d" not in df.columns:
        return "Insufficient data"
    try:
        recent = df.iloc[-20:]
        trend_slope = recent["sma_20"].iloc[-1] - recent["sma_20"].iloc[0]
        vol = recent["return_1d"].std()
        if vol > 0.04:
            return "Crisis volatility"
        if trend_slope > 0 and vol > 0.02:
            return "Bull trend"
        if trend_slope < 0 and vol > 0.02:
            return "Bear trend"
        return "Sideways"
    except Exception:
        return "Unknown"


def compute_technical_score(df: pd.DataFrame) -> float:
    try:
        if "price" not in df.columns or "sma_20" not in df.columns:
            return 0.5
        score = 0.5
        if df["price"].iloc[-1] > df["sma_20"].iloc[-1]:
            score += 0.2
        if "momentum_20" in df.columns and df["momentum_20"].iloc[-1] > 0:
            score += 0.2
        if "volatility_20" in df.columns and df["volatility_20"].iloc[-1] < 0.03:
            score += 0.1
        return float(max(0.0, min(1.0, score)))
    except Exception:
        return 0.5


def compute_macro_score(df: pd.DataFrame) -> float:
    try:
        score = 0.5
        if "inflation" in df.columns:
            val = pd.to_numeric(df["inflation"].iloc[-1], errors="coerce")
            if pd.notna(val) and val < 3.5:
                score += 0.15
        if "unemployment_rate" in df.columns:
            val = pd.to_numeric(df["unemployment_rate"].iloc[-1], errors="coerce")
            if pd.notna(val) and val < 5.0:
                score += 0.15
        if "interest_rate" in df.columns:
            val = pd.to_numeric(df["interest_rate"].iloc[-1], errors="coerce")
            if pd.notna(val) and val < 4.0:
                score += 0.1
        if "gdp" in df.columns:
            val = pd.to_numeric(df["gdp"].iloc[-1], errors="coerce")
            if pd.notna(val) and 1.8 <= val <= 2.4:
                score += 0.1
        return float(max(0.0, min(1.0, score)))
    except Exception:
        return 0.5


def compute_quant_score(df: pd.DataFrame) -> float:
    try:
        if "momentum_20" not in df.columns or "volatility_20" not in df.columns or "return_1d" not in df.columns:
            return 0.5
        score = 0.5
        if df["momentum_20"].iloc[-1] > 0:
            score += 0.2
        if df["volatility_20"].iloc[-1] < 0.03:
            score += 0.1
        if df["return_1d"].iloc[-1] > 0:
            score += 0.1
        return float(max(0.0, min(1.0, score)))
    except Exception:
        return 0.5


def compute_risk_score(df: pd.DataFrame) -> float:
    try:
        if "return_1d" not in df.columns:
            return 0.5
        returns = df["return_1d"].dropna()
        if returns.empty:
            return 0.5
        downside_prob = float((returns < 0).mean())
        return float(max(0.0, min(1.0, 1 - downside_prob)))
    except Exception:
        return 0.5


def compute_ensemble_outlook(technical: float, macro: float, quant: float, risk: float) -> str:
    score = technical * 0.35 + macro * 0.25 + quant * 0.25 + (1 - risk) * 0.15
    if score >= 0.65:
        return "Bullish"
    if score >= 0.45:
        return "Neutral"
    return "Bearish"


def estimate_probability_distribution(predictions: pd.DataFrame, last_price: float) -> dict:
    if len(predictions) <= 1:
        return {"bullish": 0.5, "neutral": 0.3, "bearish": 0.2}
    future_returns = predictions["predicted_price"].pct_change().dropna()
    bullish = float((future_returns > 0).mean())
    neutral = float(((future_returns >= -0.005) & (future_returns <= 0.005)).mean())
    bearish = float((future_returns < 0).mean())
    return {
        "bullish": bullish,
        "neutral": neutral,
        "bearish": bearish,
    }


def predict_future(
    model: dict[str, Any],
    df: pd.DataFrame,
    future_horizon: int,
    frequency: str,
    future_macro: pd.DataFrame | None = None,
    feature_columns: list[str] | None = None,
    metadata: dict | None = None,
) -> pd.DataFrame:
    last_row = df.iloc[-1]
    future_dates = make_future_dates(last_row["date"], future_horizon, frequency)
    future_df = create_future_frame(last_row, future_dates, future_macro)
    full_df = pd.concat([df, future_df], ignore_index=True, sort=False)
    full_df = compute_forecast_features(full_df)
    future_slice = full_df[full_df["date"].isin(future_dates)].copy()

    if feature_columns is None and metadata is not None:
        feature_columns = metadata.get("features")
    if feature_columns is None:
        feature_columns = [c for c in future_slice.columns if c not in ["date", "price"]]

    for col in feature_columns:
        if col not in future_slice.columns:
            future_slice[col] = 0.0

    future_X = future_slice[feature_columns].copy().fillna(0)
    if metadata is not None and metadata.get("pca_components") is not None and metadata.get("pca") is not None:
        future_X = pd.DataFrame(metadata["pca"].transform(future_X), columns=[f"pca_{i+1}" for i in range(metadata["pca"].n_components_)], index=future_X.index)

    predictions, direction_prob = regime_adjusted_predict(model, future_X, future_slice.get("market_regime"), metadata)
    future_slice["predicted_price"] = predictions
    if direction_prob is not None:
        future_slice["predicted_up_prob"] = direction_prob
    return future_slice[["date", "predicted_price"] + [c for c in future_slice.columns if c not in ["date", "price", "predicted_price"]]]


def evaluate_model(df: pd.DataFrame, model: dict[str, Any], feature_columns: list[str] | None = None, metadata: dict | None = None) -> dict:
    df_fe = feature_engineering(df)
    df_fe = assign_market_regime(df_fe)
    df_fe = encode_market_regime(df_fe)
    if feature_columns is None and metadata is not None:
        feature_columns = metadata.get("features")
    if feature_columns is None:
        feature_columns = [c for c in df_fe.columns if c not in ["date", "price"]]
    X = df_fe[feature_columns].copy().fillna(0)
    y = df_fe["price"].copy()
    if metadata is not None and metadata.get("pca_components") is not None and metadata.get("pca") is not None:
        X = pd.DataFrame(metadata["pca"].transform(X), columns=[f"pca_{i+1}" for i in range(metadata["pca"].n_components_)], index=X.index)

    predicted, direction_prob = regime_adjusted_predict(model, X, df_fe.get("market_regime"), metadata)
    mae = np.mean(np.abs(predicted - y))
    rmse = np.sqrt(np.mean((predicted - y) ** 2))
    actual_returns = y.pct_change().dropna()
    predicted_returns = pd.Series(predicted, index=y.index).pct_change().dropna()

    direction_actual = (y.diff() > 0).astype(int).iloc[1:]
    if direction_prob is not None and len(direction_prob) == len(y):
        direction_pred = (direction_prob >= 0.5).astype(int)[1:]
    else:
        direction_pred = (np.diff(predicted) > 0).astype(int) if len(predicted) > 1 else np.array([], dtype=int)

    direction_pred_arr = np.asarray(direction_pred)
    direction_actual_arr = np.asarray(direction_actual)
    min_len = min(len(direction_pred_arr), len(direction_actual_arr))
    if min_len > 0:
        direction_accuracy = float((direction_actual_arr[:min_len] == direction_pred_arr[:min_len]).mean())
        precision = float(precision_score(direction_actual_arr[:min_len], direction_pred_arr[:min_len], zero_division=0))
        recall = float(recall_score(direction_actual_arr[:min_len], direction_pred_arr[:min_len], zero_division=0))
    else:
        direction_accuracy = 0.0
        precision = 0.0
        recall = 0.0

    sharpe = float(np.mean(predicted_returns) / np.std(predicted_returns)) if predicted_returns.std(ddof=0) > 0 else 0.0
    max_dd = max_drawdown(pd.Series(predicted, index=y.index))
    profit_factor = compute_profit_factor(actual_returns, direction_pred)
    return {
        "mae": float(mae),
        "rmse": float(rmse),
        "direction_accuracy": direction_accuracy,
        "precision": precision,
        "recall": recall,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "profit_factor": profit_factor,
    }


class PriceTargetModel:
    """
    Institutional-style price target analysis combining fundamentals, technicals, and probability.
    """
    def __init__(self, price_data: pd.DataFrame, eps: float, pe_ratio: float):
        """
        price_data: pandas DataFrame with ['price', 'high', 'low'] or similar close/ohlcv columns.
        eps: trailing 12-month earnings per share.
        pe_ratio: expected P/E multiple for fundamental target.
        """
        self.df = price_data.copy()
        self.df = self.df.rename(columns={
            'Close': 'Close', 'close': 'Close',
            'High': 'High', 'high': 'High',
            'Low': 'Low', 'low': 'Low',
            'Volume': 'Volume', 'volume': 'Volume',
            'price': 'Close'
        })
        for col in ['Close', 'High', 'Low']:
            if col not in self.df.columns:
                if 'price' in self.df.columns:
                    self.df[col] = self.df['price']
                else:
                    raise ValueError(f"Price data must contain 'Close'/'close'/'price' column.")
        self.eps = eps
        self.pe_ratio = pe_ratio

    def fundamental_target(self) -> float:
        return self.eps * self.pe_ratio

    def support_resistance(self, window: int = 20) -> tuple[float, float]:
        self.df['rolling_high'] = self.df['High'].rolling(window).max()
        self.df['rolling_low'] = self.df['Low'].rolling(window).min()
        resistance = self.df['rolling_high'].iloc[-1]
        support = self.df['rolling_low'].iloc[-1]
        return support, resistance

    def trend_bias(self) -> str:
        self.df['EMA20'] = self.df['Close'].ewm(span=20).mean()
        self.df['EMA50'] = self.df['Close'].ewm(span=50).mean()
        if self.df['EMA20'].iloc[-1] > self.df['EMA50'].iloc[-1]:
            return "BULLISH"
        elif self.df['EMA20'].iloc[-1] < self.df['EMA50'].iloc[-1]:
            return "BEARISH"
        else:
            return "NEUTRAL"

    def rsi(self, period: int = 14) -> float:
        delta = self.df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]

    def volume_strength(self) -> str:
        if 'Volume' not in self.df.columns:
            return "N/A"
        avg_vol = self.df['Volume'].rolling(20).mean().iloc[-1]
        curr_vol = self.df['Volume'].iloc[-1]
        if curr_vol > avg_vol * 1.5:
            return "STRONG"
        elif curr_vol > avg_vol:
            return "MODERATE"
        else:
            return "WEAK"

    def combined_target(self) -> dict:
        fund_target = self.fundamental_target()
        support, resistance = self.support_resistance()
        trend = self.trend_bias()
        rsi_val = self.rsi()
        vol = self.volume_strength()

        if trend == "BULLISH":
            tech_weight = 0.6
            fund_weight = 0.4
        elif trend == "BEARISH":
            tech_weight = 0.7
            fund_weight = 0.3
        else:
            tech_weight = 0.5
            fund_weight = 0.5

        momentum_boost = 1.0
        if rsi_val > 60:
            momentum_boost = 1.1
        elif rsi_val < 40:
            momentum_boost = 0.9

        volume_boost = 1.0
        if vol == "STRONG":
            volume_boost = 1.1
        elif vol == "WEAK":
            volume_boost = 0.9

        final_target = (
            (fund_target * fund_weight) +
            (resistance * tech_weight)
        ) * momentum_boost * volume_boost

        score = 0
        score += 2 if trend == "BULLISH" else 0
        score += 2 if rsi_val > 50 else 0
        score += 2 if vol == "STRONG" else 1 if vol == "MODERATE" else 0
        score += 2 if final_target > self.df['Close'].iloc[-1] else 0

        if score >= 7:
            grade = "A"
        elif score >= 5:
            grade = "B"
        else:
            grade = "C"

        return {
            "Fundamental Target": round(fund_target, 2),
            "Support": round(support, 2),
            "Resistance": round(resistance, 2),
            "Final Target": round(final_target, 2),
            "Trend": trend,
            "RSI": round(rsi_val, 2),
            "Volume Strength": vol,
            "Score": score,
            "Grade": grade,
        }


st.set_page_config(page_title="Price Prediction UI", layout="wide")
st.title("Price Prediction Dashboard")

data_source = st.radio("Historical data source", ["Upload file", "Yahoo ticker", "Manual entry"], index=0)

df = None
uploaded_file = None
ticker = ""
manual_text = ""
start_date = None
end_date = None

if data_source == "Upload file":
    uploaded_file = st.file_uploader("Upload historical price data (CSV or Excel)", type=["csv", "xlsx", "xls"])
    if uploaded_file is not None:
        df = load_data(uploaded_file)
        st.subheader("Historical data preview")
        st.dataframe(df.head(10))
elif data_source == "Yahoo ticker":
    st.markdown("**Enter ticker symbol and date range:**")
    ticker = st.text_input("Ticker symbol (e.g., AAPL)", value="AAPL", key="ticker_input")
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start date", value=date(2020, 1, 1), key="start_date_input")
    end_date = col2.date_input("End date", value=date.today(), key="end_date_input")
    
    if ticker and start_date and end_date and start_date <= end_date:
        try:
            preview_df = fetch_yahoo_data(ticker, start_date.isoformat(), end_date.isoformat())
            st.subheader("Historical data preview")
            st.dataframe(preview_df, height=360)
            df = preview_df
        except Exception as e:
            st.warning(f"Unable to load ticker preview: {e}")
elif data_source == "Manual entry":
    manual_text = st.text_area(
        "Manual CSV entry (format: date,price)",
        value="date,price\n2024-01-01,100\n2024-02-01,105",
        height=200,
        key="manual_entry_input",
    )
    if manual_text and manual_text.strip():
        try:
            df = parse_manual_entry(manual_text)
            st.subheader("Historical data preview")
            st.dataframe(df.head(10))
        except Exception as e:
            st.warning(f"Unable to parse manual entry: {e}")

range_1219 = st.checkbox("Use 12-19 month price target prediction", value=False)
if range_1219:
    frequency = "m"
    horizon = 19
    st.markdown("_Using a 12-19 month monthly target window. Predictions will be shown for months 12 through 19._")
else:
    horizon = st.number_input("Future horizon", min_value=1, max_value=36, value=6)
    frequency = st.selectbox("Frequency", ["m", "q", "w", "d"], index=0, format_func=lambda x: {"m": "Monthly", "q": "Quarterly", "w": "Weekly", "d": "Daily"}[x])
future_macro_text = st.text_area(
    "Future macro/micro input (JSON or CSV)",
    value=get_default_macro_input(),
    help=(
        "Enter future macro values manually in JSON or CSV format using keys: gdp, inflation, "
        "unemployment_rate, interest_rate, trade_balance. Defaults are gdp ~2.1 (range 1.8-2.4), "
        "inflation 3.3, unemployment_rate 4.3, interest_rate 3.74."
    ),
    height=180,
)

use_past_macro_history = st.radio(
    "Use past macro history to infer future macro values?",
    ["Yes", "No"],
    index=0,
    help=(
        "If Yes, uploaded historical macro data will be used to infer missing future macro fields. "
        "If No, enter future macro values one by one below."
    ),
)
manual_macro_inputs: dict[str, float] = {}
if use_past_macro_history == "No":
    st.markdown("**Enter future macro values one by one:**")
    manual_macro_inputs = {
        "gdp": st.number_input("GDP", value=2.1, format="%.2f"),
        "inflation": st.number_input("Inflation", value=3.3, format="%.2f"),
        "unemployment_rate": st.number_input("Unemployment rate", value=4.3, format="%.2f"),
        "interest_rate": st.number_input("Interest rate", value=3.74, format="%.2f"),
        "trade_balance": st.number_input("Trade balance", value=-57.35, format="%.2f"),
    }

historical_macro_file = st.file_uploader("Optional historical macro/micro data file", type=["csv", "xlsx", "xls"])
macro_file = st.file_uploader("Optional future macro/micro input file", type=["json", "csv", "xlsx", "xls"])
alpha_vantage_api_key = st.text_input(
    "Optional Alpha Vantage API key",
    type="password",
    help="Provide your Alpha Vantage API key to automatically fetch company fundamentals.",
)
alpha_vantage_symbol = st.text_input(
    "Alpha Vantage ticker symbol",
    value="",
    help="Enter the symbol for Alpha Vantage fundamentals. Defaults to the selected Yahoo ticker if blank.",
)
st.markdown("_Use Yahoo Finance as primary historical price source. Optional Alpha Vantage fundamentals can be added automatically._")
macro_method = st.selectbox("Macro forecasting method", ["static", "growth", "none"], index=0)
pe_multiple = st.number_input("Fundamental P/E multiple", min_value=0.0, value=15.0, step=0.5, format="%.2f")

run_prediction = st.button("Run prediction")

if run_prediction:
    if data_source == "Upload file":
        if uploaded_file is None:
            st.error("❌ Please upload a historical price file before running prediction.")
            st.stop()
        else:
            try:
                df = load_data(uploaded_file)
            except Exception as e:
                st.error(f"❌ Failed to load uploaded file: {e}")
                st.stop()
    elif data_source == "Yahoo ticker":
        if not ticker or not ticker.strip():
            st.error("❌ Please enter a ticker symbol (e.g., AAPL, MSFT, GOOGL) before running prediction.")
            st.stop()
        if start_date is None or end_date is None:
            st.error("❌ Please select both start and end dates.")
            st.stop()
        if start_date > end_date:
            st.error("❌ Start date must be before end date.")
            st.stop()
        try:
            df = fetch_yahoo_data(ticker.strip(), start_date.isoformat(), end_date.isoformat())
        except ValueError as e:
            st.error(f"❌ {str(e)}")
            st.stop()
        except Exception as e:
            st.error(f"❌ Failed to fetch Yahoo ticker data: {e}")
            st.stop()
    elif data_source == "Manual entry":
        if not manual_text or not manual_text.strip():
            st.error("❌ Please provide manual price data (date,price format) before running prediction.")
            st.stop()
        else:
            try:
                df = parse_manual_entry(manual_text)
            except Exception as e:
                st.error(f"❌ Failed to parse manual entry: {e}")
                st.stop()

    if df is None or df.empty:
        st.error("❌ No data was loaded. Please check your input and try again.")
        st.stop()
    
    model, metadata, df_fe = train_model(df)
    future_dates = make_future_dates(df.iloc[-1]["date"], horizon, frequency)
    future_macro = None

    if historical_macro_file is not None:
        try:
            historical_macro = load_macro_file(historical_macro_file)
            historical_macro_reset = historical_macro.reset_index().rename(columns={"index": "date"})
            df = df.merge(historical_macro_reset, on="date", how="left")
            model, metadata, df_fe = train_model(df)
            st.success(f"✅ Merged {len(historical_macro.columns)} historical macro columns into training data")
        except Exception as e:
            st.error(f"❌ Failed to merge historical macro file: {e}")
            st.stop()

    if alpha_vantage_api_key:
        try:
            symbol = alpha_vantage_symbol.strip() or (normalize_ticker(ticker) if data_source == "Yahoo ticker" and ticker else None)
            if symbol is None:
                st.warning("Enter an Alpha Vantage ticker symbol to fetch fundamentals.")
            else:
                overview_data = fetch_alpha_vantage_overview(symbol, alpha_vantage_api_key)
                df = merge_alpha_vantage_overview(df, overview_data)
                st.success("✅ Merged Alpha Vantage fundamentals into training data")
                model, metadata, df_fe = train_model(df)
        except Exception as e:
            st.error(f"❌ Failed to fetch Alpha Vantage data: {e}")
            st.error(f"Future macro input error: {e}")
            future_macro = None
    elif macro_method == "growth":
        macro_cols = [c for c in df.columns if c in MACRO_FEATURE_ALIASES]
        if macro_cols:
            future_macro = forecast_macro_by_growth(df, future_dates, macro_cols)
        else:
            st.warning(
                "No macro columns found in historical data for growth forecasting. "
                "Upload a macro file or enter future macro values manually."
            )

    if future_macro is not None:
        ignored_macro = [c for c in future_macro.columns if c not in metadata["features"]]
        if ignored_macro:
            st.warning(
                "The following future macro fields are not present in training data and will be ignored: "
                f"{', '.join(ignored_macro)}"
            )

    metrics = evaluate_model(df, model, metadata["features"], metadata)
    predictions = predict_future(model, df, horizon, frequency, future_macro, metadata["features"], metadata)
    if range_1219:
        if len(predictions) >= 12:
            predictions = predictions.iloc[11:19].reset_index(drop=True)
        else:
            st.warning("Not enough forecast periods to show a full 12-19 month window; showing available future predictions.")
    
    # Institutional-grade price target analysis
    price_data = df[['date', 'price']].rename(columns={'price': 'Close'}).copy()
    if 'high' in df.columns:
        price_data['High'] = df['high']
    else:
        price_data['High'] = df['price'] * 1.02
    if 'low' in df.columns:
        price_data['Low'] = df['low']
    else:
        price_data['Low'] = df['price'] * 0.98
    if 'volume' in df.columns:
        price_data['Volume'] = df['volume']
    else:
        price_data['Volume'] = 1000000
    
    eps_estimate = pe_multiple if pe_multiple > 0 else 5.0
    target_model = PriceTargetModel(price_data, eps=eps_estimate, pe_ratio=15)
    analysis = target_model.combined_target()
    
    regime = detect_market_regime(df_fe)
    technical_score = compute_technical_score(df_fe)
    macro_score = compute_macro_score(df_fe)
    quant_score = compute_quant_score(df_fe)
    risk_score = compute_risk_score(df_fe)
    final_outlook = compute_ensemble_outlook(technical_score, macro_score, quant_score, risk_score)
    probabilities = estimate_probability_distribution(predictions, df["price"].iloc[-1])

    st.subheader("Evaluation")
    st.json(metrics)

    st.subheader("Institutional Analysis")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Grade", analysis["Grade"])
    col2.metric("Trend", analysis["Trend"])
    col3.metric("RSI", analysis["RSI"])
    col4.metric("Volume", analysis["Volume Strength"])
    col5.metric("Score", f"{analysis['Score']}/10")
    
    st.markdown(f"**Fundamental Target:** {analysis['Fundamental Target']:.2f}")
    st.markdown(f"**Final Target:** {analysis['Final Target']:.2f}")
    st.markdown(f"**Support:** {analysis['Support']:.2f} | **Resistance:** {analysis['Resistance']:.2f}")
    st.markdown(f"**Probability Range:** {analysis['Support']:.2f} - {analysis['Resistance']:.2f}")

    st.subheader("Regime & Outlook")
    st.markdown(f"**Regime:** {regime}")
    st.markdown(
        f"**Technical score:** {technical_score:.2f}  |  "
        f"**Macro score:** {macro_score:.2f}  |  "
        f"**Quant score:** {quant_score:.2f}  |  "
        f"**Risk score:** {risk_score:.2f}"
    )
    st.markdown(f"**Final outlook:** {final_outlook}")
    st.markdown(
        f"**Probability distribution:** Bullish {probabilities['bullish'] * 100:.0f}%, "
        f"Neutral {probabilities['neutral'] * 100:.0f}%, "
        f"Bearish {probabilities['bearish'] * 100:.0f}%"
    )

    if range_1219 and not predictions.empty:
        min_price = predictions["predicted_price"].min()
        max_price = predictions["predicted_price"].max()
        st.markdown(f"**12-19 month predicted range:** {min_price:.2f} - {max_price:.2f}")

    st.subheader("Predictions")
    st.dataframe(predictions)
    st.download_button(
        "Download predictions",
        predictions.to_csv(index=False).encode("utf-8"),
        file_name="predictions.csv",
        mime="text/csv",
    )
