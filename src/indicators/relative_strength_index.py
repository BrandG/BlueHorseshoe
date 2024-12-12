from globals import ReportSingleton
import talib as ta


class RelativeStrengthIndex:
    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data
        self.rsi_data = ta.RSI(self._data['close'],  # type: ignore
                            timeperiod=14)

    def __str__(self):
        return f'RSI: {self.rsi_data.tolist()[-1]:.2f}'

    # pylint: disable=unused-variable
    def graph(self):
        # To Do: Fill this in
        ReportSingleton().write(self.rsi_data.tolist()[-1])

    @property
    def value(self):
        if len(self.rsi_data) > 0:
            rsi = self.rsi_data.tolist()[-1]
            return {'buy': bool(rsi < 15), 'sell': bool(rsi > 85)}
        return {'buy': False, 'sell': False}
