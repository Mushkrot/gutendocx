class Loader:
    def open(self, input_path):
        raise NotImplementedError

    def save(self, document, output_path):
        raise NotImplementedError
