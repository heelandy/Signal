"""Neural-network layer (NN-001) — sequence models over candle windows ending at the signal bar.

The NN never predicts buy/sell from scratch: it answers "does this RULE-VALID setup look like the
historical winners under similar conditions?" — an advisory similarity/confidence score alongside
the tabular ML layer. Same labels, same purged validation, same promotion gates, same registry.
"""
