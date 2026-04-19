import io
import csv

class DataDrivenTestingAgent:
    def __init__(self):
        pass

    def parse_payload(self, csv_data: str) -> list:
        """Parses raw CSV data payload into parametrized test runs."""
        if not csv_data.strip():
            return []
            
        try:
            reader = csv.DictReader(io.StringIO(csv_data))
            variants = [row for row in reader]
            return variants
        except Exception as e:
            raise Exception(f"Failed to parse CSV mapping: {str(e)}")
            
    def apply_variant_to_feature(self, base_feature: str, variant: dict) -> str:
        """Applies a data variation dictionary onto a base feature testing string."""
        injected = base_feature
        for k, v in variant.items():
            injected += f" | {k}: {v}"
        return injected
