class BaseParser:
    def __init__(self, path):
        self.path = path

    def parse(self):
        raise NotImplementedError
