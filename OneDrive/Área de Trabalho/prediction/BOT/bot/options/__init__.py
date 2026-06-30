"""Options engine — the computation Pine CANNOT do (chain/IV/premium/Greeks).

Black-Scholes pricing + Greeks + IV solve (pricing.py) and the naked / debit / credit call-and-put
structures translated from an ORB signal (strategies.py). Uses the real OPRA chain when available,
else a BS estimate. Output feeds the signal the user acts on at their discretion.
"""
