import pandas as pd

EXCEL_PATH = "CDT AITP Go Live (2).xlsx"

class Catalog:
    def __init__(self, variants, fillers):
        self.variants = variants      # All rows (each row = a product/variant)
        self.fillers = fillers

def load_catalog(excel_path: str = EXCEL_PATH):
    xls = pd.ExcelFile(excel_path)

    variants = pd.read_excel(xls, sheet_name="Attraction Groups")
    fillers = pd.read_excel(xls, sheet_name="Free-time attractions")

    return Catalog(variants=variants, fillers=fillers)