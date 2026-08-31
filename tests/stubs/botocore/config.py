class Config:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def merge(self, other):
        return self
