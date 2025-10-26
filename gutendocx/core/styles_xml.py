class StylesXml:
    def apply_overrides(self, document, overrides):
        raise NotImplementedError

    def remap_styles(self, document, rules):
        raise NotImplementedError
