from pathlib import Path

test_data_path = Path(__file__).parent

# Make the path available as the default object when importing test_data
__all__ = []  # Prevent wildcard imports from exposing `path`
