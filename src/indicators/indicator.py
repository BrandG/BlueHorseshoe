from abc import abstractmethod


class Indicator:
    @abstractmethod
    def __init__(self, data):
        self.update

    @abstractmethod
    def update(self, data):
        self.data = data

    @property
    @abstractmethod
    def value(self):
        raise NotImplementedError("Subclasses should implement this method")

    @abstractmethod
    def graph(self):
        raise NotImplementedError("Subclasses should implement this method")