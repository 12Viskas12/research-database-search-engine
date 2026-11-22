import os
from abc import ABC, abstractmethod


class BaseParser(ABC):
    extensions = ()
    registry = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for extension in cls.extensions:
            BaseParser.registry[extension] = cls

    def __init__(self, path):
        self.path = path
        self.size = max(1, os.path.getsize(path))
        self.consumed = 0
        self.fraction = 0.0

    @abstractmethod
    def rows(self):
        raise NotImplementedError

    def parse(self):
        return self.rows()

    @property
    def progress(self):
        if self.fraction:
            return min(1.0, self.fraction)
        return min(1.0, self.consumed / self.size)

    @classmethod
    def supports(cls, extension):
        return extension.lower() in cls.registry


class TableParser(BaseParser):
    @staticmethod
    def header_of(values):
        return [str(h).strip() if h is not None and str(h).strip() else f"col{i + 1}" for i, h in enumerate(values)]

    @staticmethod
    def record_of(header, values):
        return {
            (header[i] if i < len(header) else f"col{i + 1}"): v
            for i, v in enumerate(values)
        }
