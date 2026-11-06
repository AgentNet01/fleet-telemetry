"""The money rule (COMMERCE.md): never list or order at a loss after every fee; profit >= $1.50 and >= 10%.

Jack, Oct 28: "An item should never be priced at something where ordering it would take a loss, including the
fees. And we should be sure of that." Every price and every supplier order is checked here, nowhere else.
Buyer sales tax is collected and remitted by the marketplace, so it is never our cost; but eBay's and Etsy's
payment fee is charged on the total including it, so fees use the real tax at order time and TAX_BUFFER before.
"""
import math

MIN_PROFIT = 1.50
MIN_MARGIN = 0.10
DAILY_CAP = 50.00            # automatic supplier spend per hub-PC calendar day
TAX_BUFFER = 0.12            # above the highest US combined sales-tax rate; used when the buyer's tax isn't known yet

# fee = on_price * price + on_total * (price + tax) + fixed, fixed = small when price <= split else big
FEES = {
    # https://www.ebay.com/help/selling/fees-credits-invoices/selling-fees?id=4822 (most categories), re-check before go-live
    "ebay": {"on_price": 0.0, "on_total": 0.136, "small": 0.30, "big": 0.40, "split": 10.00},
    # https://www.etsy.com/legal/fees: 6.5% transaction on item + shipping, 3% + $0.25 payment (US), $0.20 listing
    "etsy": {"on_price": 0.065, "on_total": 0.03, "small": 0.45, "big": 0.45, "split": 0.0},
}


def _up(x):
    return math.ceil(round(x * 100, 6)) / 100        # round 6 first: 8.38 * 100 is 838.0000000001


def fees(channel, price, tax=None):
    """Channel fees on one sale, rounded up to the cent (rounding never hides a loss)."""
    f = FEES[channel]
    tax = price * TAX_BUFFER if tax is None else tax
    return _up(f["on_price"] * price + f["on_total"] * (price + tax) + (f["small"] if price <= f["split"] else f["big"]))


def profit(channel, price, cost, tax=None):
    return round(price - fees(channel, price, tax) - cost, 2)


def ok(channel, price, cost, tax=None):
    return profit(channel, price, cost, tax) >= max(MIN_PROFIT, round(MIN_MARGIN * price, 2))


def floor(channel, cost):
    """Lowest price that passes ok() for this landed cost, before the buyer's tax is known."""
    f = FEES[channel]
    k = f["on_price"] + f["on_total"] * (1 + TAX_BUFFER)
    p = 0.0
    for fixed in (f["small"], f["big"]):
        p = max((cost + fixed + MIN_PROFIT) / (1 - k), (cost + fixed) / (1 - k - MIN_MARGIN))
        if p <= f["split"] or fixed == f["big"]:
            break
    p = max(_up(p), _up(f["split"] + 0.01) if p > f["split"] > 0 else 0)
    while not ok(channel, p, cost):                   # a cent or two from rounding fees up
        p = round(p + 0.01, 2)
    return p


def lines(channel, sale, cost_parts, tax):
    """The breakdown Jack sees when an order or listing is refused."""
    cost = round(sum(cost_parts.values()), 2)
    parts = ", ".join(f"{k} ${v:.2f}" for k, v in cost_parts.items())
    return (f"sale ${sale:.2f}, {parts}, fee ${fees(channel, sale, tax):.2f}, profit ${profit(channel, sale, cost, tax):.2f} "
            f"(needs ${max(MIN_PROFIT, round(MIN_MARGIN * sale, 2)):.2f})")
