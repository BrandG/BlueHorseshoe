import talib as ta

from globals import ReportSingleton


class StochasticOscillator:

    def __init__(self, data):
        self.update(data)

    def update(self, data):
        self._data = data
        self._slowk, self._slowd = ta.STOCH(self._data['high'], self._data['low'], self._data['close'],  # type: ignore
                                fastk_period=5, slowk_period=3, slowk_matype=0,
                                slowd_period=3, slowd_matype=0)

    @property
    def value(self):
        slowd_list = self._slowd.tolist()
        slowk_list = self._slowk.tolist()

        buy = sell = hold = False
        if slowk_list[-1] > slowd_list[-1] and slowk_list[-2] <= slowd_list[-2]:
            buy = True
        elif slowk_list[-1] < slowd_list[-1] and slowk_list[-2] >= slowd_list[-2]:
            sell = True
        else:
            hold = True
        return {'buy': buy, 'sell': sell, 'hold': hold}

    # pylint: disable=unused-variable
    def graph(self):
        # To Do: Fill this in
        ReportSingleton().write(f'{self._slowd}, {self._slowk}')
