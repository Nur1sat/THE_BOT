from __future__ import annotations

from xau_signal_bot.services.models import Decision, RiskPlan


class RiskService:
    @staticmethod
    def calculate(decision: Decision, entry: float, atr: float) -> RiskPlan | None:
        if decision == Decision.NO_TRADE or atr <= 0:
            return None
        risk = 1.5 * atr
        if decision == Decision.LONG:
            stop_loss = entry - risk
            take_profit_1 = entry + risk
            take_profit_2 = entry + (1.5 * risk)
            take_profit_3 = entry + (2.0 * risk)
        else:
            stop_loss = entry + risk
            take_profit_1 = entry - risk
            take_profit_2 = entry - (1.5 * risk)
            take_profit_3 = entry - (2.0 * risk)
        return RiskPlan(
            entry=round(entry, 2),
            stop_loss=round(stop_loss, 2),
            take_profit_1=round(take_profit_1, 2),
            take_profit_2=round(take_profit_2, 2),
            take_profit_3=round(take_profit_3, 2),
            risk_reward="1:1.5 primary",
            risk_per_unit=round(risk, 2),
        )
